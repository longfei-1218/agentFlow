"""对话模式（R5.1）：一个会话绑定一个流程，每轮用户消息创建一个 run。

助手回复不落独立表：`chat_turns.run_id` 指向 runs，读取时按 run 终态回填，
这样运行中/失败/刷新都能从同一份事实源恢复。
"""
from typing import Literal

from pydantic import Field, field_validator

from app.models.flow import CamelModel


class ConversationCreate(CamelModel):
    flow_id: str
    title: str = ""


class Conversation(CamelModel):
    id: str
    flow_id: str
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
