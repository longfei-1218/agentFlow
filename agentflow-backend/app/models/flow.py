"""Flow DSL 契约：与前端 src/types/flow.ts 逐字段对齐。

内部用 snake_case，API 序列化自动转 camelCase（alias_generator=to_camel），
这样前端拿到的 JSON 与静态设计稿里的字段完全一致。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

NodeType = Literal[
    "start", "agent", "condition", "loop", "human", "end",
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
    # 发布指针：只有发布才推进；回滚会把它指回历史版本
    version: int = 1
    # 1 = R1–R5 旧 DSL；2 = start/agent/condition/loop/human/end
    dsl_version: int = 1
    # 草稿 / 发布指纹缓存，只由保存与发布反推
    draft_hash: str | None = None
    published_hash: str | None = None
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    created_at: str | None = None
    updated_at: str | None = None


class FlowCreate(CamelModel):
    """创建请求：id/version/时间戳由服务端生成。

    nodes/edges 为 None 表示「调用方没提供结构」，服务端补默认流程；
    显式传空数组是合法输入（空白画布），不能和「没传」混为一谈。

    base_updated_at 是可选乐观锁：调用方带上「我加载时看到的 updatedAt」，
    服务端发现已经被别人改过就拒绝覆盖（防两个标签页互相回滚配置）。
    """
    name: str = "未命名流程"
    dsl_version: int = 2
    nodes: list[FlowNode] | None = None
    edges: list[FlowEdge] | None = None
    base_updated_at: str | None = None


class ValidationIssue(CamelModel):
    node_id: str | None = None
    field: str | None = None
    message: str


class ValidationResult(CamelModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
