"""Agent 对话契约：作用域 = agentId + flowId? + nodeId?。

库内直聊只有 agentId；从流程节点进入时带 flowId/nodeId，
同一 Agent 在不同流程/节点各聊各的，不共享历史。
"""
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.flow import CamelModel


class ConversationCreate(CamelModel):
    agent_id: str
    flow_id: str | None = None
    node_id: str | None = None
    title: str = ""


class Conversation(CamelModel):
    id: str
    agent_id: str
    flow_id: str | None = None
    node_id: str | None = None
    title: str
    created_at: str
    updated_at: str


class ChatMessage(CamelModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    turn_id: str
    run_id: str | None = None
    status: str | None = None
    error: str | None = None
    tokens: int = 0
    cost: float = 0.0


class ConversationDetail(Conversation):
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatTurnCreate(CamelModel):
    content: str = Field(min_length=1, max_length=8000)
    # 变量面板：除 query 之外的必选变量
    variables: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class ChatTurnResult(CamelModel):
    conversation_id: str
    turn_id: str
    run_id: str
    status: str
