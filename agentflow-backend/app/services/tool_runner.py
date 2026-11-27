"""工具执行器（R3）：参数校验 → 幂等查缓存 → 带超时重试地调用 → 落调用记录。

几个刻意的取舍：
- **不做「工具级沙箱」**：这是本地原型，HTTP 工具能打任何地址；只靠 human 节点审批高危工具。
- **重试只对「可能重试」的失败重试**：连接错误 / 超时 / 5xx 重试，4xx 是参数问题，重试只会重复挨骂。
- **幂等是「同工具+同参数，TTL 内直接复用上次成功结果」**：不给每个工具做业务幂等键，
  那是业务语义；原型层能证明「重复调用不会重复下单」就够了。
- 参数字符串化后再做 URL/body 插值：工具作者写 `{{city}}`，模型给的是 JSON 值，不能假设一定是 str。
"""
import ast
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import orjson

from app.config import settings
from app.models.tool import ToolDef, ToolInvocation
from app.resources import catalog
from app.services import env_config, tool_repo
from app.services.event_bus import utc_now

HTTP_TIMEOUT = "timeout"
RETRYABLE_HTTP = {500, 502, 503, 504}


class ToolError(RuntimeError):
    def __init__(self, message: str, code: str = "TOOL_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ToolArgsError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="TOOL_ARGS_INVALID")


class ToolHttpError(ToolError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message, code="TOOL_HTTP_ERROR")
        self.http_status = status


# 测试注入点：单测用 httpx.MockTransport 换掉真实网络，产品代码保持不变
_client_factory = lambda timeout: httpx.AsyncClient(timeout=timeout)  # noqa: E731


def set_client_factory(factory) -> None:  # pragma: no cover - 仅供测试
    global _client_factory
    _client_factory = factory


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return orjson.dumps(value).decode()
    return str(value)


def render(value: str, args: dict[str, Any]) -> str:
    """`{{arg}}` 插值；未提供的占位符保留原样，方便用户看出模板写错了。"""
    result = value
    for key, item in args.items():
        result = result.replace("{{" + key + "}}", _stringify(item))
    return result


def _tool_env_scope(tool: ToolDef) -> dict[str, str]:
    try:
        return env_config.resolve_env_map(tool.env)
    except env_config.EnvConfigError as exc:
        raise ToolError(str(exc), code="TOOL_ENV_MISSING") from exc


def _expand_config(value: str | None, scope: dict[str, str]) -> str:
    try:
        return env_config.expand_env(value, scope=scope)
    except env_config.EnvConfigError as exc:
        raise ToolError(str(exc), code="TOOL_ENV_MISSING") from exc


_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> None:
    """按 JSON Schema 的常用子集校验；只查「必填 / 类型 / enum」，不做 full JSON Schema。"""
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    missing = [key for key in required if key not in args]
    if missing:
        raise ToolArgsError(f"缺少必填参数: {', '.join(missing)}（Schema 要求 {', '.join(required)}）")

    for key, value in args.items():
        prop = properties.get(key)
        if not prop:
            continue
        expected = prop.get("type")
        python_type = _TYPE_MAP.get(str(expected))
        if python_type and not isinstance(value, python_type):
            raise ToolArgsError(f"参数 {key} 应为 {expected}，实际是 {type(value).__name__}")
        enum = prop.get("enum")
        if enum and value not in enum:
            raise ToolArgsError(f"参数 {key} 只能取 {enum}")


def _canonical(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def idempotency_key(tool: ToolDef, args: dict[str, Any]) -> str | None:
    if tool.idempotency != "key" or not args:
        return None
    digest = hashlib.sha1(f"{tool.id}:{_canonical(args)}".encode("utf-8")).hexdigest()
    return f"idem_{digest[:24]}"


def _builtin_call(name: str, args: dict[str, Any]) -> Any:
    if name == "echo":
        return {"echo": args.get("text", "")}
    if name == "now":
        tz_name = str(args.get("tz") or "Asia/Shanghai")
        try:
            tz = timezone(timedelta(hours=8)) if tz_name in ("Asia/Shanghai", "UTC+8") else timezone.utc
        except Exception:  # noqa: BLE001 - 时区名写错就退回 UTC，别让工具挂掉
            tz = timezone.utc
        now = datetime.now(tz)
        return {"iso": now.isoformat(), "tz": tz_name, "timestamp": int(now.timestamp())}
    if name == "calc":
        return {"result": _safe_eval(str(args.get("expression") or ""))}
    try:
        return catalog.invoke_builtin(
            name, args, {"artifact_dir": settings.ARTIFACT_DIR}
        )
    except catalog.BuiltinToolError as exc:
        raise ToolError(str(exc), code=exc.code) from exc


def _safe_eval(expression: str) -> float:
    """只允许数字与 + - * / ** 括号：用 AST 白名单，绝不 eval 用户输入。"""
    if not expression.strip():
        raise ToolArgsError("expression 不能为空")
    tree = ast.parse(expression, mode="eval")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ToolArgsError("除数不能为 0")
                return left / right
            return left ** right
        raise ToolArgsError("表达式只支持数字、四则运算与括号")

    return walk(tree)


async def _http_call(tool: ToolDef, args: dict[str, Any]) -> tuple[Any, int | None]:
    scope = _tool_env_scope(tool)
    url = _expand_config(render(tool.url, args), scope)
    headers = {
        key: _expand_config(render(value, args), scope)
        for key, value in (tool.headers or {}).items()
    }
    method = tool.method.upper()

    kwargs: dict[str, Any] = {"headers": headers}
    if method in ("GET", "DELETE"):
        kwargs["params"] = {key: _stringify(value) for key, value in args.items()}
    else:
        if tool.body_template:
            rendered = _expand_config(render(tool.body_template, args), scope)
            try:
                kwargs["json"] = orjson.loads(rendered)
            except orjson.JSONDecodeError as exc:
                raise ToolError(f"body_template 不是合法 JSON: {exc}", code="TOOL_BAD_TEMPLATE") from exc
        else:
            kwargs["json"] = args

    async with _client_factory(httpx.Timeout(tool.timeout_ms / 1000)) as client:
        response = await client.request(method, url, **kwargs)
        status = response.status_code
        text = response.text
        try:
            payload: Any = orjson.loads(text)
        except orjson.JSONDecodeError:
            payload = text[:4000]

    if status >= 400:
        raise ToolHttpError(status, f"HTTP {status}: {str(payload)[:300]}")
    return payload, status


async def invoke(
    tool: ToolDef,
    args: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    node_id: str | None = None,
    timeout_ms: int | None = None,
    retries: int | None = None,
    skip_idempotency: bool = False,
) -> ToolInvocation:
    """执行一次工具调用并落库。失败抛出 ToolError，调用方决定「让 run 失败」还是「回给模型」。"""
    args = dict(args or {})
    validate_args(tool.params_schema, args)

    if not tool.enabled:
        raise ToolError(f"工具 {tool.name} 已停用", code="TOOL_DISABLED")

    effective_timeout = timeout_ms or tool.timeout_ms
    effective_retries = tool.retries if retries is None else retries

    idem_key = None if skip_idempotency else idempotency_key(tool, args)
    if idem_key:
        since = (datetime.now(timezone.utc) - timedelta(seconds=tool.idempotency_ttl_s)).isoformat()
        cached = await tool_repo.find_recent_ok_by_idem(idem_key, since)
        if cached:
            invocation = ToolInvocation(
                id=f"inv_{uuid.uuid4().hex[:10]}",
                tool_id=tool.id,
                tool_name=tool.name,
                run_id=run_id,
                node_id=node_id,
                args=args,
                status="ok",
                attempts=0,
                latency_ms=0,
                http_status=cached.http_status,
                result=cached.result,
                idem_key=idem_key,
                idem_hit=True,
            )
            return await tool_repo.record_invocation(invocation)

    started = time.perf_counter()
    last_error = ""
    attempts = 0
    http_status: int | None = None
    result: Any = None
    success = False
    is_timeout = False

    for attempt in range(effective_retries + 1):
        attempts = attempt + 1
        try:
            if tool.kind == "builtin":
                result = _builtin_call(tool.builtin or "", args)
            else:
                result, http_status = await _http_call(tool, args)
            success = True
            break
        except ToolArgsError:
            # 参数/Schema 不合法：重试只是重复挨骂，直接抛给调用方
            raise
        except ToolHttpError as exc:
            last_error = str(exc)
            http_status = exc.http_status
            retryable = exc.http_status in RETRYABLE_HTTP
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            is_timeout = isinstance(exc, httpx.TimeoutException)
            retryable = True
        except ToolError:
            # body 模板坏、内置工具不存在这类是配置问题，重试没意义
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            retryable = False

        if not retryable or attempt >= effective_retries:
            break
        # 指数退避，封顶 1s：原型不必做抖动
        await _sleep(min(tool.backoff_ms * (2 ** attempt), 1000) / 1000)

    latency_ms = int((time.perf_counter() - started) * 1000)

    status = "ok" if success else ("timeout" if is_timeout else "error")

    invocation = ToolInvocation(
        id=f"inv_{uuid.uuid4().hex[:10]}",
        tool_id=tool.id,
        tool_name=tool.name,
        run_id=run_id,
        node_id=node_id,
        args=args,
        status=status,
        attempts=attempts,
        latency_ms=latency_ms,
        http_status=http_status,
        result=result if success else None,
        error=None if success else last_error,
        idem_key=idem_key,
        idem_hit=False,
    )
    await tool_repo.record_invocation(invocation)

    if not success:
        raise ToolError(
            f"{tool.name} 调用失败（{attempts} 次尝试，{latency_ms}ms）：{last_error}",
            code="TOOL_TIMEOUT" if is_timeout else "TOOL_INVOKE_FAILED",
        )
    return invocation


async def _sleep(seconds: float) -> None:
    import asyncio

    if seconds > 0:
        await asyncio.sleep(seconds)


def fc_schema(tool: ToolDef) -> dict[str, Any]:
    """转成 OpenAI tools 数组里的单个元素。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or f"调用工具 {tool.name}",
            "parameters": tool.params_schema,
        },
    }


async def fc_schemas(tool_ids: list[str]) -> list[dict[str, Any]]:
    if not tool_ids:
        return []
    try:
        tools = await tool_repo.get_tools_by_ids(tool_ids)
    except tool_repo.ToolNotFound as exc:
        # 绑定了一个已被删掉的工具：属于流程配置问题，按工具错误报出来才看得懂
        raise ToolError(str(exc), code="TOOL_NOT_FOUND") from exc
    for tool in tools:
        if not tool.enabled:
            raise ToolError(f"工具 {tool.name} 已停用，仍在流程里被引用", code="TOOL_DISABLED")
    return [fc_schema(tool) for tool in tools]


async def resolve_by_name(tools: list[ToolDef], name: str) -> ToolDef:
    for tool in tools:
        if tool.name == name:
            return tool
    raise ToolError(f"模型调用了未绑定的工具: {name}", code="TOOL_NOT_BOUND")
