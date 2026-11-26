"""Run / RunEvent 契约：对齐技术文档 4.2 与 SSE 协议 7.2。"""
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from app.models.flow import CamelModel

EventType = Literal[
    "run_started", "node_started", "node_completed",
    "token", "tool_call", "tool_result",
    "human_required", "run_completed", "run_failed",
]


class RunStatus(str, Enum):
    """注意：不用 enum.StrEnum（3.11+），这里退成 str+Enum 以兼容 Python 3.10。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Run(CamelModel):
    id: str
    flow_id: str
    flow_version: int
    status: RunStatus
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    token_usage: int = 0
    cost_estimate: float = 0.0
    started_at: str | None = None
    finished_at: str | None = None


class RunEvent(CamelModel):
    id: str
    run_id: str
    seq: int
    type: EventType
    node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class RunCreate(CamelModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
