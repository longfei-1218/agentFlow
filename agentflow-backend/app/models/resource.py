"""资源导入结果契约。"""
from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

ResourceImportKind = Literal["mcp_local", "mcp_remote", "http_tool"]


class ResourceImportResult(CamelModel):
    ok: bool
    kind: ResourceImportKind
    status: Literal["installed", "verified", "rejected"]
    name: str = ""
    target_id: str | None = None
    package_path: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None
    code: str | None = None
    verified_at: str | None = None


class ResourceOverview(CamelModel):
    owner_id: str
    builtin_tools: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bases: list[dict[str, Any]] = Field(default_factory=list)
