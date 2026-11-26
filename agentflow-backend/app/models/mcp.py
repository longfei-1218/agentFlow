"""MCP Server 与工具调用的契约（R5）。

只做 stdio 传输：本地单用户场景下，MCP 的价值是「把一个本地可执行的工具进程接进画布」，
stdio 正好覆盖（npx / uvx / python 脚本都行）。HTTP/SSE 传输留到需要多机共享时再加，
不在这一轮假装支持。
"""
from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

Transport = Literal["stdio"]


class MCPServerDef(CamelModel):
    id: str
    name: str
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_s: float = Field(default=15, ge=1, le=300)
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class MCPServerCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    transport: Transport = "stdio"
    command: str = Field(min_length=1, max_length=512)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_s: float = Field(default=15, ge=1, le=300)
    enabled: bool = True


class MCPToolInfo(CamelModel):
    name: str
    description: str = ""
    # CamelModel 会自动序列化成 inputSchema
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPCallRequest(CamelModel):
    tool_name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class MCPProbeResult(CamelModel):
    ok: bool
    tools: list[MCPToolInfo] = Field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None
    code: str | None = None


class MCPCallResult(CamelModel):
    ok: bool
    result: Any = None
    raw: Any = None
    latency_ms: int = 0
    error: str | None = None
    code: str | None = None
