"""工具 / MCP 配置里的环境变量展开。

约定：
- 配置文本（URL、Header、Body、MCP command/args/cwd/env 值）里写 `${NAME}`；
- 运行时从「进程环境变量 + 资源自己的 env 字典」解析；
- 缺失变量不静默保留占位符，直接抛 `EnvConfigError`，让调用方翻译成业务错误码。
  静默保留会把 `Bearer ${TOKEN}` 原样发给上游，最后只看到 401，排查成本更高。

这里刻意不读 `app.config.settings`：进程环境变量本来就是运行时输入，
工具 / MCP 的 env 字典是资源级覆盖，两者合并即可。
"""
import os
import re
from pathlib import Path

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _base_scope() -> dict[str, str]:
    """进程环境 + 后端 `.env`。

    `pydantic-settings` 只把 `.env` 读进 `Settings` 对象，不会写回 `os.environ`；
    而工具 / MCP 的 `${VAR}` 需要一个统一作用域，所以这里显式合并。
    真实进程环境优先于 `.env`，便于部署时覆盖。
    """
    merged = dict(os.environ)
    env_file = Path(os.environ.get("AGENTFLOW_ENV_FILE", ".env")).expanduser()
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None and key not in merged:
                    merged[key] = value
        except Exception:  # noqa: BLE001 - 读 .env 失败不能阻断工具调用
            pass
    return merged


class EnvConfigError(ValueError):
    """配置引用了不存在的环境变量。"""

    def __init__(self, missing: list[str], where: str = "") -> None:
        self.missing = sorted(set(missing))
        suffix = f"（位置：{where}）" if where else ""
        super().__init__(f"缺少环境变量: {', '.join(self.missing)}{suffix}")


def expand_env(value: str | None, *, scope: dict[str, str] | None = None) -> str:
    """把 `${NAME}` 换成环境变量值；没有占位符时原样返回。"""
    text = "" if value is None else str(value)
    if "${" not in text:
        return text

    merged = _base_scope()
    if scope:
        merged.update({str(key): str(item) for key, item in scope.items()})

    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in merged:
            missing.append(name)
            return match.group(0)
        return str(merged[name])

    result = ENV_REF.sub(replace, text)
    if missing:
        raise EnvConfigError(missing)
    return result


def resolve_env_map(
    values: dict[str, str] | None,
    *,
    base_scope: dict[str, str] | None = None,
) -> dict[str, str]:
    """解析资源自己的 env 字典。

    资源 env 的 key 也会进入作用域，所以 `${API_TOKEN}` 可以直接引用
    `env={"API_TOKEN": "..."}`；资源 env 的值本身也可以写 `${OS_VAR}`。
    """
    raw = {str(key): str(value) for key, value in (values or {}).items()}
    merged = _base_scope()
    if base_scope:
        merged.update({str(key): str(value) for key, item in base_scope.items()})
    merged.update(raw)

    resolved: dict[str, str] = {}
    for key, value in raw.items():
        resolved[key] = expand_env(value, scope=merged)
    return resolved
