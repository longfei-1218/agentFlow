"""外部资源导入：本地 MCP zip、远程 MCP manifest、HTTP 工具 manifest。

安全边界（当前是「简单隔离」版本）：
- zip 解压拒绝绝对路径、`..`、符号链接、压缩炸弹；
- 本地 MCP 只在 staging 目录里探测，验证通过才移动到 users/<owner>/mcp；
- 子进程只继承当前进程环境 + manifest 声明的 env，不额外注入；
- 远程 MCP 只做 HTTP JSON-RPC / SSE 响应兼容，不做任意 URL 白名单（后续多人版本再加）。
"""
import json
import os
import shutil
import stat
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.mcp import MCPServerCreate, MCPServerDef
from app.models.resource import ResourceImportResult
from app.models.tool import ToolCreate
from app.resources import catalog
from app.services import knowledge_repo, mcp_client, mcp_repo, tool_repo
from app.services.event_bus import utc_now

MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_ENTRIES = 500


class ImportFailure(RuntimeError):
    def __init__(self, message: str, code: str = "RESOURCE_IMPORT_FAILED") -> None:
        super().__init__(message)
        self.code = code


def _base() -> Path:
    return Path(settings.RESOURCE_DATA_DIR).expanduser().resolve()


def _owner() -> str:
    return (settings.RESOURCE_OWNER_ID or "local").strip() or "local"


def _staging_dir() -> Path:
    path = _base() / "staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _owner_dir(kind: str) -> Path:
    path = _base() / "users" / _owner() / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_manifest(raw: str | bytes, source: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ImportFailure(f"{source} 不是合法 JSON: {exc}", "RESOURCE_MANIFEST_INVALID") from exc
    if not isinstance(data, dict):
        raise ImportFailure(f"{source} 必须是 JSON 对象", "RESOURCE_MANIFEST_INVALID")
    return data


def _validate_common(manifest: dict[str, Any]) -> str:
    name = str(manifest.get("name") or "").strip()
    if not name:
        raise ImportFailure("manifest 缺少 name", "RESOURCE_MANIFEST_INVALID")
    if str(manifest.get("schemaVersion") or 1) != "1":
        raise ImportFailure("只支持 schemaVersion=1", "RESOURCE_MANIFEST_INVALID")
    return name


def _safe_extract(zip_bytes: bytes, target: Path) -> None:
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ImportFailure(f"压缩包超过 {MAX_ZIP_BYTES} bytes", "RESOURCE_ZIP_TOO_LARGE")
    target.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(__import__("io").BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ImportFailure(f"不是有效 zip: {exc}", "RESOURCE_ZIP_INVALID") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ImportFailure(f"zip 文件数超过 {MAX_ZIP_ENTRIES}", "RESOURCE_ZIP_TOO_LARGE")
        total = sum(info.file_size for info in infos if not info.is_dir())
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ImportFailure("zip 解压后体积过大", "RESOURCE_ZIP_TOO_LARGE")

        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ImportFailure(f"zip 包含非法路径: {info.filename}", "RESOURCE_ZIP_UNSAFE")
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ImportFailure(f"zip 不允许符号链接: {info.filename}", "RESOURCE_ZIP_UNSAFE")
            destination = (target / name).resolve()
            try:
                destination.relative_to(target.resolve())
            except ValueError as exc:
                raise ImportFailure(f"zip 路径越界: {info.filename}", "RESOURCE_ZIP_UNSAFE") from exc
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _find_package_root(staging: Path) -> tuple[Path, dict[str, Any]]:
    manifests = list(staging.rglob("manifest.json"))
    if not manifests:
        raise ImportFailure("zip 里没有 manifest.json", "RESOURCE_MANIFEST_MISSING")
    if len(manifests) > 1:
        raise ImportFailure("zip 里只能有一个 manifest.json", "RESOURCE_MANIFEST_INVALID")
    manifest_path = manifests[0]
    manifest = _json_manifest(manifest_path.read_text(encoding="utf-8"), str(manifest_path))
    return manifest_path.parent, manifest


def _mcp_create(
    *,
    name: str,
    transport: str,
    command: str,
    args: list[str],
    url: str,
    headers: dict[str, str],
    env: dict[str, str],
    cwd: str | None,
    timeout_s: float,
    package_path: str | None,
    manifest: dict[str, Any],
) -> MCPServerCreate:
    return MCPServerCreate(
        name=name,
        transport=transport,
        command=command,
        args=args,
        url=url,
        headers=headers,
        env=env,
        cwd=cwd,
        timeout_s=timeout_s,
        enabled=True,
        package_path=package_path,
        manifest_json=manifest,
        source="import",
    )


async def _probe(server: MCPServerCreate) -> list[dict[str, Any]]:
    candidate = MCPServerDef(id="probe", **server.model_dump())
    tools, _ = await mcp_client.probe_tools(candidate)
    return [tool.model_dump(by_alias=True) for tool in tools]


async def import_mcp_zip(zip_bytes: bytes) -> ResourceImportResult:
    stage = _staging_dir() / f"mcp_{uuid.uuid4().hex[:10]}"
    installed_dir: Path | None = None
    try:
        _safe_extract(zip_bytes, stage)
        package_dir, manifest = _find_package_root(stage)
        _validate_common(manifest)
        if str(manifest.get("kind") or "") != "mcp":
            raise ImportFailure("zip 的 kind 必须是 mcp", "RESOURCE_KIND_INVALID")
        if str(manifest.get("transport") or "stdio") != "stdio":
            raise ImportFailure("本地 MCP 包只支持 stdio", "RESOURCE_TRANSPORT_UNSUPPORTED")

        runtime = manifest.get("runtime") or {}
        entrypoint = str(runtime.get("entrypoint") or "server.py")
        server_path = (package_dir / entrypoint).resolve()
        try:
            server_path.relative_to(package_dir.resolve())
        except ValueError as exc:
            raise ImportFailure(f"entrypoint 越界: {entrypoint}", "RESOURCE_PATH_INVALID") from exc
        if not server_path.is_file():
            raise ImportFailure(f"entrypoint 不存在: {entrypoint}", "RESOURCE_ENTRYPOINT_MISSING")

        name = str(manifest.get("name") or manifest.get("id"))
        env = {str(k): str(v) for k, v in (manifest.get("env") or {}).items()}
        timeout_s = float(manifest.get("timeoutS") or 20)
        candidate = _mcp_create(
            name=name,
            transport="stdio",
            command=sys.executable,
            args=[str(server_path)],
            url="",
            headers={},
            env=env,
            cwd=str(package_dir),
            timeout_s=timeout_s,
            package_path=None,
            manifest=manifest,
        )
        tools = await _probe(candidate)

        resource_id = str(manifest.get("id") or name)
        safe_id = "".join(ch for ch in resource_id if ch.isalnum() or ch in "-_")[:40] or "mcp"
        installed_dir = _owner_dir("mcp") / f"{safe_id}-{uuid.uuid4().hex[:8]}"
        shutil.move(str(package_dir), str(installed_dir))

        installed_server = _mcp_create(
            name=name,
            transport="stdio",
            command=sys.executable,
            args=[str(installed_dir / entrypoint)],
            url="",
            headers={},
            env=env,
            cwd=str(installed_dir),
            timeout_s=timeout_s,
            package_path=str(installed_dir),
            manifest=manifest,
        )
        installed_server.status = "installed"
        installed_server.verified_at = utc_now()
        saved = await mcp_repo.create_server(installed_server)
        return ResourceImportResult(
            ok=True,
            kind="mcp_local",
            status="installed",
            name=name,
            target_id=saved.id,
            package_path=str(installed_dir),
            tools=tools,
            verified_at=saved.verified_at,
        )
    except mcp_repo.MCPNameConflict as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if installed_dir is not None:
            shutil.rmtree(installed_dir, ignore_errors=True)
        return ResourceImportResult(
            ok=False, kind="mcp_local", status="rejected", name="", message=str(exc), code="MCP_NAME_CONFLICT"
        )
    except (ImportFailure, mcp_client.MCPError, OSError, ValueError) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if installed_dir is not None:
            shutil.rmtree(installed_dir, ignore_errors=True)
        return ResourceImportResult(
            ok=False,
            kind="mcp_local",
            status="rejected",
            name="",
            message=str(exc),
            code=getattr(exc, "code", "RESOURCE_IMPORT_FAILED"),
        )
    finally:
        if stage.exists() and not any(stage.iterdir()):
            stage.rmdir()


async def import_mcp_remote(manifest_raw: str) -> ResourceImportResult:
    try:
        manifest = _json_manifest(manifest_raw, "远程 MCP manifest")
        name = _validate_common(manifest)
        if str(manifest.get("kind") or "mcp") != "mcp":
            raise ImportFailure("kind 必须是 mcp", "RESOURCE_KIND_INVALID")
        if str(manifest.get("transport") or "") != "http":
            raise ImportFailure("远程 MCP manifest 的 transport 必须是 http", "RESOURCE_TRANSPORT_UNSUPPORTED")
        candidate = _mcp_create(
            name=name,
            transport="http",
            command="",
            args=[],
            url=str(manifest.get("url") or ""),
            headers={str(k): str(v) for k, v in (manifest.get("headers") or {}).items()},
            env={str(k): str(v) for k, v in (manifest.get("env") or {}).items()},
            cwd=None,
            timeout_s=float(manifest.get("timeoutS") or 20),
            package_path=None,
            manifest=manifest,
        )
        tools = await _probe(candidate)
        candidate.status = "installed"
        candidate.verified_at = utc_now()
        saved = await mcp_repo.create_server(candidate)
        return ResourceImportResult(
            ok=True,
            kind="mcp_remote",
            status="installed",
            name=name,
            target_id=saved.id,
            tools=tools,
            verified_at=saved.verified_at,
        )
    except mcp_repo.MCPNameConflict as exc:
        return ResourceImportResult(
            ok=False, kind="mcp_remote", status="rejected", name="", message=str(exc), code="MCP_NAME_CONFLICT"
        )
    except (ImportFailure, mcp_client.MCPError, ValueError) as exc:
        return ResourceImportResult(
            ok=False,
            kind="mcp_remote",
            status="rejected",
            name="",
            message=str(exc),
            code=getattr(exc, "code", "RESOURCE_IMPORT_FAILED"),
        )


async def import_http_tool(manifest_raw: str) -> ResourceImportResult:
    try:
        manifest = _json_manifest(manifest_raw, "HTTP 工具 manifest")
        name = _validate_common(manifest)
        if str(manifest.get("kind") or "") != "http_tool":
            raise ImportFailure("kind 必须是 http_tool", "RESOURCE_KIND_INVALID")
        url = str(manifest.get("url") or "").strip()
        if not url:
            raise ImportFailure("HTTP 工具必须配置 url", "RESOURCE_MANIFEST_INVALID")
        payload = ToolCreate(
            name=name,
            description=str(manifest.get("description") or ""),
            kind="http",
            method=str(manifest.get("method") or "GET"),
            url=url,
            headers={str(k): str(v) for k, v in (manifest.get("headers") or {}).items()},
            env={str(k): str(v) for k, v in (manifest.get("env") or {}).items()},
            body_template=manifest.get("bodyTemplate"),
            params_schema=manifest.get("paramsSchema") or {"type": "object", "properties": {}},
            timeout_ms=int(manifest.get("timeoutMs") or 5000),
            retries=int(manifest.get("retries") or 1),
            backoff_ms=int(manifest.get("backoffMs") or 400),
            idempotency=str(manifest.get("idempotency") or "key"),
            idempotency_ttl_s=int(manifest.get("idempotencyTtlS") or 600),
            risk=str(manifest.get("risk") or "low"),
            enabled=bool(manifest.get("enabled", True)),
            source="import",
            verified_at=utc_now(),
        )
        saved = await tool_repo.create_tool(payload)
        return ResourceImportResult(
            ok=True,
            kind="http_tool",
            status="installed",
            name=name,
            target_id=saved.id,
            verified_at=saved.verified_at,
        )
    except tool_repo.ToolNameConflict as exc:
        return ResourceImportResult(
            ok=False, kind="http_tool", status="rejected", name="", message=str(exc), code="TOOL_NAME_CONFLICT"
        )
    except (ImportFailure, ValueError) as exc:
        return ResourceImportResult(
            ok=False,
            kind="http_tool",
            status="rejected",
            name="",
            message=str(exc),
            code=getattr(exc, "code", "RESOURCE_IMPORT_FAILED"),
        )


async def overview() -> dict[str, Any]:
    tools = await tool_repo.list_tools()
    servers = await mcp_repo.list_servers()
    knowledge = await knowledge_repo.list_kbs()
    return {
        "ownerId": _owner(),
        "builtinTools": catalog.list_builtins(),
        "tools": [tool.model_dump(by_alias=True) for tool in tools],
        "mcpServers": [server.model_dump(by_alias=True) for server in servers],
        "knowledgeBases": [kb.model_dump(by_alias=True) for kb in knowledge],
    }

