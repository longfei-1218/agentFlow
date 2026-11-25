"""Flow DSL 契约：与前端 src/types/flow.ts 逐字段对齐。

内部用 snake_case，API 序列化自动转 camelCase（alias_generator=to_camel），
这样前端拿到的 JSON 与静态设计稿里的字段完全一致。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

NodeType = Literal[
    "input", "llm", "prompt", "tool", "mcp",
    "skill", "knowledge", "condition", "loop", "human", "output",
]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FlowNode(CamelModel):
    id: str
    type: NodeType
    position: dict[str, float]
    config: dict[str, Any] = Field(default_factory=dict)


class FlowEdge(CamelModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None


class Flow(CamelModel):
    id: str
    name: str
    version: int = 1
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    created_at: str | None = None
    updated_at: str | None = None


class FlowCreate(CamelModel):
    """创建请求：id/version/时间戳由服务端生成。"""
    name: str = "未命名流程"
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)


class ValidationIssue(CamelModel):
    node_id: str | None = None
    field: str | None = None
    message: str


class ValidationResult(CamelModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
