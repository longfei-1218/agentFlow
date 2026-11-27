"""Flow v2 节点注册表：只有 6 类节点。

流程只负责「开始 → 调 Agent / 分支 / 循环 / 审批 → 结束」；
prompt、llm、tool、mcp、knowledge 全部收进 Agent 资源。
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from app.models.agent import AgentVariable
from app.models.flow import CamelModel, NodeType

Category = Literal["基础", "Agent", "控制"]


class NodeConfig(BaseModel):
    """配置模型基类：允许 DSL 里残留旧字段，不因为多一个键就校验失败。"""

    model_config = ConfigDict(
        extra="allow", alias_generator=to_camel, populate_by_name=True
    )


class StartConfig(NodeConfig):
    variables: list[AgentVariable] = Field(
        default_factory=lambda: [
            AgentVariable(key="query", label="用户输入", type="string", required=True)
        ],
        title="流程输入变量",
        description="运行时从 /run 的 inputs 取值；下游用 {{start.<key>}} 引用",
    )


class AgentConfig(NodeConfig):
    agent_id: str = Field(default="", title="Agent", description="全局 Agent 库里的 ID")
    input_map: dict[str, str] = Field(
        default_factory=dict,
        title="变量映射",
        description='Agent 变量 → 流程表达式，如 {"query": "{{start.query}}"}',
    )


class ConditionConfig(NodeConfig):
    expression: str = Field(
        default="{{score}} > 0.8",
        title="条件表达式",
        description="支持 {{start.query}} / {{nodeId.output.field}}；true 走真分支",
        min_length=1,
    )


class LoopConfig(NodeConfig):
    max_rounds: int = Field(default=3, title="最大轮次", ge=1, le=32)
    exit_condition: str = Field(
        default="",
        title="退出条件",
        description="留空表示只按最大轮次退出；如 {{node.output.done}} == true",
    )


class HumanConfig(NodeConfig):
    message: str = Field(default="是否允许执行该高危操作？", title="审批提示", min_length=1)
    timeout: float = Field(default=300, title="超时（秒）", ge=1, le=86400)


class EndConfig(NodeConfig):
    outputs: list[str] | dict[str, str] = Field(
        default_factory=list,
        title="最终输出",
        description=(
            '留空取最后一个 Agent 的 text；列表如 ["reply_1.output.text"]，'
            '或对象如 {"text": "{{reply_1.output.text}}"}'
        ),
    )


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
            (field_.alias or name): field_.get_default(call_default_factory=True)
            for name, field_ in self.config_model.model_fields.items()
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
        type="start", label="开始", icon="▶", category="基础", color="#6b7280",
        description="声明流程输入变量，运行时从 /run 的 inputs 取值",
        config_model=StartConfig, outputs=["variables"],
    ),
    NodeSpec(
        type="agent", label="Agent", icon="✦", category="Agent", color="#3b82f6",
        description="调用全局 Agent；inputMap 把流程变量映射成 Agent 变量，产物写 nodes.<nodeId>.output",
        config_model=AgentConfig, inputs=["variables"], outputs=["output"],
    ),
    NodeSpec(
        type="condition", label="分支", icon="⑂", category="控制", color="#f59e0b",
        description="按表达式选择 true/false 分支，条件边只走其中一条",
        config_model=ConditionConfig, inputs=["variables"], outputs=["true", "false"],
    ),
    NodeSpec(
        type="loop", label="循环", icon="↻", category="控制", color="#f59e0b",
        description="有界循环：达到最大轮次或退出条件为真走 done，否则走 body",
        config_model=LoopConfig, inputs=["variables"], outputs=["variables"],
    ),
    NodeSpec(
        type="human", label="审批", icon="☝", category="控制", color="#f59e0b",
        description="中断并等待人工审批后继续",
        config_model=HumanConfig, inputs=["variables"], outputs=["approved"],
    ),
    NodeSpec(
        type="end", label="结束", icon="⏹", category="基础", color="#6b7280",
        description="按 outputs 声明产出最终结果；留空取最后一个 Agent 的 text",
        config_model=EndConfig, inputs=["variables"], outputs=["outputs"],
    ),
]

_SPECS: dict[str, NodeSpec] = {spec.type: spec for spec in _SPEC_LIST}

# 有默认值但业务上必须非空
REQUIRED_NON_EMPTY = {
    ("agent", "agent_id"),
    ("condition", "expression"),
    ("human", "message"),
}


def all_specs() -> list[NodeSpec]:
    return _SPEC_LIST


def get_spec(node_type: str) -> NodeSpec | None:
    return _SPECS.get(node_type)


def categories() -> list[str]:
    return ["基础", "Agent", "控制"]


def validate_config(node_type: str, config: dict[str, Any]) -> list[str]:
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
