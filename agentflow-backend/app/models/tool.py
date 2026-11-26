"""工具定义与调用记录契约（R3）。

和节点 Schema 一样，工具的 `params_schema` 是标准 JSON Schema：
- 后端拿它做调用前参数校验；
- 前端拿它渲染试跑表单；
- 真正 Function Calling 时，它原样塞进请求体的 `tools[].function.parameters`，
  模型看到的就是这一份定义——不存在「给模型看的」和「执行时校验的」两套。
"""
from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

ToolKind = Literal["http", "builtin"]
Risk = Literal["low", "medium", "high"]
IdemMode = Literal["none", "key"]
BuiltinName = Literal["echo", "now", "calc"]

# 内置工器的默认参数 Schema：没有网络也能把「真执行」这条路走通
BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "echo": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "原样返回的文本"}},
        "required": ["text"],
    },
    "now": {
        "type": "object",
        "properties": {"tz": {"type": "string", "description": "时区名，默认本地 Asia/Shanghai"}},
    },
    "calc": {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "四则运算表达式，如 (1+2)*3"}},
        "required": ["expression"],
    },
}


class ToolDef(CamelModel):
    id: str
    name: str
    description: str = ""
    kind: ToolKind = "http"
    builtin: BuiltinName | None = None
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    params_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    retries: int = Field(default=1, ge=0, le=5)
    backoff_ms: int = Field(default=400, ge=0, le=5000)
    idempotency: IdemMode = "key"
    idempotency_ttl_s: int = Field(default=600, ge=0, le=86400)
    risk: Risk = "low"
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class ToolCreate(CamelModel):
    """创建/更新请求体：id 与时间戳由服务端生成。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    kind: ToolKind = "http"
    builtin: BuiltinName | None = None
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    params_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    retries: int = Field(default=1, ge=0, le=5)
    backoff_ms: int = Field(default=400, ge=0, le=5000)
    idempotency: IdemMode = "key"
    idempotency_ttl_s: int = Field(default=600, ge=0, le=86400)
    risk: Risk = "low"
    enabled: bool = True


class ToolInvocation(CamelModel):
    id: str
    tool_id: str
    tool_name: str
    run_id: str | None = None
    node_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "timeout"] = "ok"
    attempts: int = 0
    latency_ms: int = 0
    http_status: int | None = None
    result: Any = None
    error: str | None = None
    idem_key: str | None = None
    idem_hit: bool = False
    created_at: str | None = None


class ToolTestRequest(CamelModel):
    args: dict[str, Any] = Field(default_factory=dict)
    # 默认不查缓存：试跑就是为了看「这一次」真实发生了什么；
    # 打开后可以连点两次验证幂等命中（第二次 attempts=0、idemHit=true）
    use_idempotency: bool = False
