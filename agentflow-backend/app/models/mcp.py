"""MCP Server 与工具调用的契约。

本地 MCP 走 stdio：后端启动一个子进程，用一行一条 JSON-RPC 通信；
远程 MCP 走 http：POST JSON-RPC，兼容 JSON / SSE 响应，保留 Mcp-Session-Id。
"""

from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

Transport = Literal["stdio", "http"]


class MCPServerDef(CamelModel):
    id: str
    name: str
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_s: float = Field(default=15, ge=1, le=300)
    enabled: bool = True
    # 资源包元数据
    package_path: str | None = None
    manifest_json: dict[str, Any] | None = None
    source: Literal["registry", "resource_package", "import"] = "registry"
    status: Literal["installed", "verified", "staged", "rejected"] = "installed"
    verified_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MCPServerCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_s: float = Field(default=15, ge=1, le=300)
    enabled: bool = True
    package_path: str | None = None
    manifest_json: dict[str, Any] | None = None
    source: Literal["registry", "resource_package", "import"] = "registry"
    status: Literal["installed", "verified", "staged", "rejected"] = "installed"
    verified_at: str | None = None


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
