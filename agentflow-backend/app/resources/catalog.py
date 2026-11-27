"""受信任资源包 Catalog。

目录约定：
    resources/
      builtin_tools/<id>/manifest.json + tool.py
      mcp/<id>/manifest.json + server.py
      knowledge/<id>/manifest.json + documents/

主程序不直接 import 具体资源；内置工具按 manifest 的 runtime.entrypoint 动态加载，
MCP / 知识库由各自的 Store 读取 manifest。`AGENTFLOW_RESOURCES_DIR` 可以覆盖仓库目录，
测试或部署时可以把资源目录挂到别处。
"""
import importlib.util
import json
import os
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


class BuiltinToolError(RuntimeError):
    def __init__(self, message: str, code: str = "TOOL_BUILTIN_FAILED") -> None:
        super().__init__(message)
        self.code = code


def resource_root() -> Path:
    raw = os.environ.get("AGENTFLOW_RESOURCES_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "resources").resolve()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuiltinToolError(f"资源 manifest 读取失败: {path}: {exc}", "RESOURCE_MANIFEST_INVALID") from exc
    if not isinstance(data, dict):
        raise BuiltinToolError(f"资源 manifest 必须是对象: {path}", "RESOURCE_MANIFEST_INVALID")
    return data


@lru_cache(maxsize=1)
def builtin_manifests() -> dict[str, tuple[Path, dict[str, Any]]]:
    """返回 name/alias → (包目录, manifest)。

    一个包可以有 aliases，例如 render_interview_repo 同时保留 render_interview_report。
    """
    index: dict[str, tuple[Path, dict[str, Any]]] = {}
    root = resource_root() / "builtin_tools"
    if not root.is_dir():
        return index
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifest = _load_manifest(manifest_path)
        package_dir = manifest_path.parent
        names = [str(manifest.get("name") or manifest.get("id") or package_dir.name)]
        names.extend(str(item) for item in (manifest.get("aliases") or []))
        for name in dict.fromkeys(names):
            index[name] = (package_dir, manifest)
    return index


def clear_cache() -> None:
    builtin_manifests.cache_clear()
    _modules.clear()


def list_builtins() -> list[dict[str, Any]]:
    """按主名称去重，返回前端内置工具下拉需要的结构。"""
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for name, (_, manifest) in builtin_manifests().items():
        primary = str(manifest.get("name") or manifest.get("id") or name)
        if name != primary or primary in seen:
            continue
        seen.add(primary)
        items.append(
            {
                "name": primary,
                "description": str(manifest.get("description") or ""),
                "paramsSchema": manifest.get("paramsSchema") or {"type": "object", "properties": {}},
            }
        )
    return items


def builtin_schema(name: str) -> dict[str, Any] | None:
    item = builtin_manifests().get(name)
    if not item:
        return None
    return item[1].get("paramsSchema") or {"type": "object", "properties": {}}


_modules: dict[str, ModuleType] = {}


def _load_module(package_dir: Path, manifest: dict[str, Any], name: str) -> ModuleType:
    runtime = manifest.get("runtime") or {}
    entrypoint = str(runtime.get("entrypoint") or "tool.py")
    path = (package_dir / entrypoint).resolve()
    try:
        path.relative_to(package_dir.resolve())
    except ValueError as exc:
        raise BuiltinToolError(f"内置工具入口越界: {entrypoint}", "RESOURCE_PATH_INVALID") from exc
    if not path.is_file():
        raise BuiltinToolError(f"内置工具入口不存在: {path}", "RESOURCE_ENTRYPOINT_MISSING")

    cache_key = f"{name}:{path.stat().st_mtime_ns}"
    if cache_key in _modules:
        return _modules[cache_key]

    module_name = f"agentflow_resource_{name}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise BuiltinToolError(f"无法加载内置工具入口: {path}", "RESOURCE_ENTRYPOINT_INVALID")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _modules[cache_key] = module
    return module


def invoke_builtin(name: str, args: dict[str, Any], context: dict[str, Any]) -> Any:
    item = builtin_manifests().get(name)
    if not item:
        raise BuiltinToolError(f"未知内置工具: {name}", "TOOL_NOT_FOUND")
    package_dir, manifest = item
    module = _load_module(package_dir, manifest, name)
    callable_name = str((manifest.get("runtime") or {}).get("callable") or "run")
    func = getattr(module, callable_name, None)
    if not callable(func):
        raise BuiltinToolError(
            f"内置工具 {name} 没有实现 {callable_name}(args, context)",
            "RESOURCE_CALLABLE_MISSING",
        )
    try:
        return func(args, context)
    except BuiltinToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BuiltinToolError(f"内置工具 {name} 执行失败: {exc}", "TOOL_BUILTIN_FAILED") from exc
