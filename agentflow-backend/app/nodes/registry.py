"""节点类型注册表：每类节点一个 Pydantic 配置模型，Schema 由模型反推。

为什么用 Pydantic 而不是手写 JSON Schema：
- 后端要拿它做 flow 校验（类型/范围/空值），前端要拿它渲染表单，两边必须同一份定义；
- 手写 schema 和校验逻辑是两份东西，改一处忘一处就会出现「界面让填、后端不认」。

约定：config 里的键继续用 snake_case（与既有 DSL 一致，不走 camelCase 别名）。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.flow import CamelModel, NodeType

Category = Literal["基础", "模型", "工具", "控制"]


class NodeConfig(BaseModel):
    """配置模型基类：允许 DSL 里残留旧字段，不因为多一个键就校验失败。"""

    model_config = ConfigDict(extra="allow")


class InputConfig(NodeConfig):
    name: str = Field(default="query", title="变量名", description="运行时从 inputs 取值的键")
    type: str = Field(default="string", title="类型", json_schema_extra={"enum": ["string", "number", "boolean"]})
    # 类型可以是 number/boolean，默认值就不能锁死成字符串，否则声明一个数字入参会校验失败
    default: Any = Field(default="", title="默认值", description="inputs 未提供时使用")


class LLMConfigModel(NodeConfig):
    model: str = Field(default="", title="模型", description="留空则用系统设置里的默认模型")
    temperature: float = Field(default=0.7, title="Temperature", ge=0, le=2)
    max_tokens: int = Field(default=1024, title="Max tokens", ge=1, le=32000)
    system: str = Field(default="你是一个有帮助的助手。", title="System Prompt", min_length=1)
    tool_ids: list[str] = Field(
        default_factory=list,
        title="绑定工具",
        description="从工具管理里选；模型会自己决定何时调用，调用结果会回填给模型",
    )


class PromptConfig(NodeConfig):
    template: str = Field(
        default="请回答：{{query}}",
        title="模板字符串",
        description="用 {{变量名}} 插值，可引用上游写入的变量",
        min_length=1,
    )


class ToolConfig(NodeConfig):
    tool_id: str = Field(default="", title="工具", description="工具管理里注册的工具")
    args_template: str = Field(
        default="{}",
        title="参数模板",
        description='JSON，支持 {{变量}} 插值，如 {"city": "{{query}}"}；超时/重试/幂等跟随工具定义',
    )


class MCPConfig(NodeConfig):
    server_id: str = Field(default="", title="MCP Server")
    tool_name: str = Field(default="", title="工具名称")


class SkillConfig(NodeConfig):
    flow_id: str = Field(default="", title="子流程 ID")


class KnowledgeConfig(NodeConfig):
    kb_id: str = Field(default="", title="知识库 ID")
    top_k: int = Field(default=4, title="Top K", ge=1, le=20)
    rerank: bool = Field(default=False, title="启用重排")


class ConditionConfig(NodeConfig):
    expression: str = Field(
        default="{{score}} > 0.8",
        title="条件表达式",
        description="如 {{score}} > 0.8；true 走「真」分支的连线，false 走「假」分支",
        min_length=1,
    )


class LoopConfig(NodeConfig):
    max_rounds: int = Field(default=3, title="最大轮次", ge=1, le=32)
    exit_condition: str = Field(
        default="",
        title="退出条件",
        description="留空表示只按最大轮次退出；如 {{done}} == true。为真时立刻走 done 边",
    )


class HumanConfig(NodeConfig):
    message: str = Field(default="是否允许执行该高危操作？", title="审批提示", min_length=1)
    timeout: float = Field(default=300, title="超时（秒）", ge=1, le=86400)


class OutputConfig(NodeConfig):
    fields: list[str] = Field(
        default_factory=lambda: ["text"],
        title="输出字段",
        description="按顺序从最终变量表里取这些键作为 outputs",
    )


class _NoConfig(NodeConfig):
    """input 之外的「无额外配置」节点用不到，保留占位意义。"""


class NodeSpec(CamelModel):
    type: NodeType
    label: str
    icon: str
    category: Category
    color: str
    description: str
    config_model: type[NodeConfig] = Field(exclude=True)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    implemented: bool = True

    def config_schema(self) -> dict[str, Any]:
        schema = self.config_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def default_config(self) -> dict[str, Any]:
        return {
            name: field.get_default(call_default_factory=True)
            for name, field in self.config_model.model_fields.items()
        }

    def to_api(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "icon": self.icon,
            "category": self.category,
            "color": self.color,
            "description": self.description,
            "configSchema": self.config_schema(),
            "defaultConfig": self.default_config(),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "implemented": self.implemented,
        }


_SPEC_LIST: list[NodeSpec] = [
    NodeSpec(
        type="input", label="入口", icon="⇥", category="基础", color="#6b7280",
        description="声明一个运行时输入变量，值来自 /run 的 inputs",
        config_model=InputConfig, outputs=["variables"],
    ),
    NodeSpec(
        type="output", label="出口", icon="⇤", category="基础", color="#6b7280",
        description="按字段列表产出 outputs",
        config_model=OutputConfig, inputs=["variables"],
    ),
    NodeSpec(
        type="llm", label="模型", icon="✦", category="模型", color="#3b82f6",
        description="调用 OpenAI 兼容接口，流式吐 token",
        config_model=LLMConfigModel, inputs=["variables"], outputs=["text"],
    ),
    NodeSpec(
        type="prompt", label="模板", icon="T", category="模型", color="#3b82f6",
        description="用 {{var}} 插值拼出文本，不调用模型",
        config_model=PromptConfig, inputs=["variables"], outputs=["text"],
    ),
    NodeSpec(
        type="tool", label="工具", icon="⚙", category="工具", color="#10b981",
        description="调用工具管理里注册的工具（HTTP / 内置），带超时、重试与幂等",
        config_model=ToolConfig, inputs=["variables"], outputs=["result"],
    ),
    NodeSpec(
        type="mcp", label="MCP", icon="⊕", category="工具", color="#10b981",
        description="调用 MCP Server 上的工具（R5 实装）",
        config_model=MCPConfig, inputs=["variables"], outputs=["result"], implemented=False,
    ),
    NodeSpec(
        type="skill", label="子流程", icon="⤴", category="工具", color="#10b981",
        description="把另一个流程当子流程调用（R5 实装）",
        config_model=SkillConfig, inputs=["variables"], outputs=["variables"], implemented=False,
    ),
    NodeSpec(
        type="knowledge", label="知识", icon="▤", category="工具", color="#10b981",
        description="检索知识库并注入上下文（R5 实装）",
        config_model=KnowledgeConfig, inputs=["query"], outputs=["context"], implemented=False,
    ),
    NodeSpec(
        type="condition", label="分支", icon="⑂", category="控制", color="#f59e0b",
        description="按表达式选择 true/false 分支，由图引擎的条件边只走其中一条（R4）",
        config_model=ConditionConfig, inputs=["variables"], outputs=["true", "false"],
    ),
    NodeSpec(
        type="loop", label="循环", icon="↻", category="控制", color="#f59e0b",
        description="有界循环：达到最大轮次或退出条件为真时走 done 边，否则走 body 边（R4）",
        config_model=LoopConfig, inputs=["variables"], outputs=["variables"],
    ),
    NodeSpec(
        type="human", label="人工", icon="☝", category="控制", color="#f59e0b",
        description="中断并等待人工审批后继续",
        config_model=HumanConfig, inputs=["variables"], outputs=["approved"],
    ),
]

_SPECS: dict[str, NodeSpec] = {spec.type: spec for spec in _SPEC_LIST}


def all_specs() -> list[NodeSpec]:
    return _SPEC_LIST


def get_spec(node_type: str) -> NodeSpec | None:
    return _SPECS.get(node_type)


def categories() -> list[str]:
    return ["基础", "模型", "工具", "控制"]


# 这些字段「有默认值但业务上必须非空」，只靠 min_length 表达不了（默认值本身合法）
REQUIRED_NON_EMPTY = {
    ("input", "name"),
    ("llm", "system"),
    ("prompt", "template"),
    ("condition", "expression"),
    ("human", "message"),
    ("tool", "tool_id"),
    ("tool", "args_template"),
}


def validate_config(node_type: str, config: dict[str, Any]) -> list[str]:
    """返回人类可读的问题列表；空列表表示配置合法。

    这里刻意不抛异常：校验要把问题汇总成 ValidationIssue 列表，一次性告诉用户。
    """
    spec = get_spec(node_type)
    if spec is None:
        return [f"未知节点类型: {node_type}"]

    problems: list[str] = []
    try:
        parsed = spec.config_model.model_validate(config or {})
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "(根)"
            problems.append(f"字段 {location}: {error['msg']}")
        return problems

    for field_name in spec.config_model.model_fields:
        if (node_type, field_name) not in REQUIRED_NON_EMPTY:
            continue
        value = getattr(parsed, field_name, None)
        if isinstance(value, str) and not value.strip():
            problems.append(f"字段 {field_name} 不能为空")
    return problems
