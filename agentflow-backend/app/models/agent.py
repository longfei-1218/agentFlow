"""Agent v2 契约：全局可复用资源，流程只引用 agentId。

一个 Agent 把自己的输入变量、提示词、资源、模型、输出契约收在一起；
流程层不再出现 prompt / llm / tool / mcp / knowledge 这些细粒度节点。
"""
import re
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.flow import CamelModel, ValidationIssue

VariableType = Literal["string", "number", "boolean", "json"]
ResourceKind = Literal["tool", "mcp", "knowledge"]

VARIABLE_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class AgentVariable(CamelModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = ""
    type: VariableType = "string"
    required: bool = True
    default: Any = None
    description: str = ""

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        if not VARIABLE_KEY_RE.match(value):
            raise ValueError("变量 key 只能包含字母、数字、下划线，且不能以数字开头")
        return value


class AgentPrompt(CamelModel):
    system: str = "你是一个有帮助的助手。"
    template: str = Field(min_length=1)


class AgentResource(CamelModel):
    kind: ResourceKind
    id: str = Field(min_length=1)
    alias: str = Field(min_length=1, max_length=64)
    # MCP 导入时选定的工具；tool / knowledge 忽略
    tools: list[str] = Field(default_factory=list)
    # knowledge 专用：用哪个变量做检索 query
    query_var: str = "query"
    top_k: int = Field(default=4, ge=1, le=20)
    rerank: bool = False


class AgentModelConfig(CamelModel):
    name: str = ""
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=32000)
    max_tool_rounds: int = Field(default=4, ge=0, le=16)


class AgentOutput(CamelModel):
    description: str = ""
    # 可选 JSON Schema；不填时输出固定为 {"text": string}
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class AgentCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    variables: list[AgentVariable] = Field(default_factory=list)
    prompt: AgentPrompt = Field(
        default_factory=lambda: AgentPrompt(template="请回答用户的问题。")
    )
    resources: list[AgentResource] = Field(default_factory=list)
    model: AgentModelConfig = Field(default_factory=AgentModelConfig)
    output: AgentOutput = Field(default_factory=AgentOutput)


class Agent(AgentCreate):
    id: str
    created_at: str
    updated_at: str
    # 发布指针：0 表示从未发布；回滚会把指针指回历史版本，不会改动历史版本号
    version: int = 0
    draft_hash: str | None = None
    published_hash: str | None = None


class AgentValidationResult(CamelModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentRunRequest(CamelModel):
    variables: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(CamelModel):
    agent_id: str
    outputs: dict[str, Any]
    text: str = ""
    tokens: int = 0
    cost: float = 0.0
    steps: int = 0
    model: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_calls: list[dict[str, Any]] = Field(default_factory=list)


class AgentResourceToken(CamelModel):
    """prompt 里解析出的 @ 资源引用。"""

    kind: Literal["kb", "tool", "mcp"]
    alias: str
    tool: str | None = None


def parse_resource_tokens(template: str) -> list[AgentResourceToken]:
    """解析 `@kb[别名]` / `@tool[别名]` / `@mcp[别名.工具]`。

    别名是 Agent 内稳定标识，不是资源库名字；资源库改名不会破坏 prompt。
    """
    tokens: list[AgentResourceToken] = []
    for kind, body in re.findall(r"@(kb|tool|mcp)\[([^\]]+)\]", template or ""):
        body = body.strip()
        if not body:
            continue
        if kind == "mcp":
            if "." not in body:
                raise ValueError("MCP 引用必须写成 @mcp[别名.工具名]")
            alias, tool = body.rsplit(".", 1)
            tokens.append(AgentResourceToken(kind="mcp", alias=alias, tool=tool))
        else:
            tokens.append(AgentResourceToken(kind=kind, alias=body))
    return tokens
