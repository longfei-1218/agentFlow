"""Agent 定义校验：变量、资源别名、@ 引用、输出 Schema。

保存和单独 validate 走同一份规则；运行期还会再校验一次资源是否仍存在。
"""
import json
import re
from typing import Any

from app.models.agent import (
    AgentCreate,
    AgentResource,
    AgentValidationResult,
    AgentVariable,
    parse_resource_tokens,
)
from app.models.flow import ValidationIssue
from app.services import knowledge_repo, mcp_client, mcp_repo, tool_repo

VAR_REF_RE = re.compile(r"{{[^{}]*}}")
VAR_NAME_RE = re.compile(r"{{(\w+)}}")


def _issue(field: str, message: str) -> ValidationIssue:
    return ValidationIssue(field=field, message=message)


def _default_matches_type(var: AgentVariable) -> bool:
    if var.default is None or var.default == "":
        return True
    if var.type == "string":
        return isinstance(var.default, str)
    if var.type == "number":
        return isinstance(var.default, (int, float)) and not isinstance(var.default, bool)
    if var.type == "boolean":
        return isinstance(var.default, bool)
    return isinstance(var.default, (dict, list))


def _schema_shape_errors(schema: dict[str, Any]) -> list[str]:
    if not isinstance(schema, dict):
        return ["输出 schema 必须是 JSON 对象"]
    problems: list[str] = []
    schema_type = schema.get("type")
    if schema_type is not None and schema_type != "object":
        problems.append("输出固定是 JSON 对象，schema.type 只能是 object")
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        problems.append("schema.properties 必须是对象")
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            problems.append("schema.required 必须是字符串数组")
        elif isinstance(properties, dict):
            missing = [name for name in required if name not in properties]
            if missing:
                problems.append(f"schema.required 里的字段没有定义 properties: {missing}")
    return problems


async def _check_resource(resource: AgentResource) -> str | None:
    """返回人类可读错误；None 表示资源存在且启用。"""
    if resource.kind == "tool":
        try:
            tool = await tool_repo.get_tool(resource.id)
        except tool_repo.ToolNotFound as exc:
            return str(exc)
        if not tool.enabled:
            return f"工具「{tool.name}」已停用"
        return None

    if resource.kind == "knowledge":
        try:
            await knowledge_repo.get_kb(resource.id)
        except knowledge_repo.KBNotFound as exc:
            return str(exc)
        return None

    try:
        server = await mcp_repo.get_server(resource.id)
    except mcp_repo.MCPServerNotFound as exc:
        return str(exc)
    if not server.enabled:
        return f"MCP Server「{server.name}」已停用"
    if not resource.tools:
        return "MCP 资源至少要导入一个工具"
    return None


async def validate_agent(payload: AgentCreate) -> AgentValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[str] = []

    if not payload.name.strip():
        errors.append(_issue("name", "Agent 名称不能为空"))
    if not payload.prompt.template.strip():
        errors.append(_issue("prompt.template", "提示词模板不能为空"))

    keys: set[str] = set()
    for index, var in enumerate(payload.variables):
        if var.key in keys:
            errors.append(_issue(f"variables[{index}].key", f"变量 key 重复: {var.key}"))
        keys.add(var.key)
        if not _default_matches_type(var):
            errors.append(
                _issue(
                    f"variables[{index}].default",
                    f"默认值与类型 {var.type} 不匹配: {var.default!r}",
                )
            )

    aliases: set[str] = set()
    kb_aliases: set[str] = set()
    referenced_kb: set[str] = set()
    for index, res in enumerate(payload.resources):
        prefix = f"resources[{index}]"
        if res.alias in aliases:
            errors.append(_issue(f"{prefix}.alias", f"资源别名重复: {res.alias}"))
        aliases.add(res.alias)
        if res.kind == "knowledge":
            kb_aliases.add(res.alias)
            if res.query_var not in keys:
                errors.append(
                    _issue(
                        f"{prefix}.query_var",
                        f"检索变量 {res.query_var} 不在变量定义里",
                    )
                )
        problem = await _check_resource(res)
        if problem:
            errors.append(_issue(prefix, problem))

    try:
        tokens = parse_resource_tokens(payload.prompt.template)
    except ValueError as exc:
        errors.append(_issue("prompt.template", str(exc)))
        tokens = []

    for token in tokens:
        if token.kind == "kb":
            if token.alias not in kb_aliases:
                errors.append(_issue("prompt.template", f"@kb[{token.alias}] 没有对应的知识库资源"))
            referenced_kb.add(token.alias)
        else:
            expected = "knowledge" if token.kind == "kb" else token.kind
            matches = [res for res in payload.resources if res.alias == token.alias]
            if not matches:
                errors.append(
                    _issue("prompt.template", f"@{token.kind}[{token.alias}] 没有对应的资源")
                )
            elif matches[0].kind != expected:
                errors.append(
                    _issue(
                        "prompt.template",
                        f"@{token.kind}[{token.alias}] 指向的资源类型是 {matches[0].kind}",
                    )
                )
            elif token.kind == "mcp" and token.tool not in matches[0].tools:
                errors.append(
                    _issue(
                        "prompt.template",
                        f"@mcp[{token.alias}.{token.tool}] 没有在导入的工具列表里",
                    )
                )

    used_vars = set(VAR_NAME_RE.findall(payload.prompt.template))
    unknown_vars = sorted(used_vars - keys)
    if unknown_vars:
        errors.append(_issue("prompt.template", f"提示词引用了未定义变量: {unknown_vars}"))

    for alias in sorted(kb_aliases - referenced_kb):
        warnings.append(f"知识库资源「{alias}」已导入但提示词没有 @，本轮不会检索")

    if payload.output.schema_ is not None:
        for problem in _schema_shape_errors(payload.output.schema_):
            errors.append(_issue("output.schema", problem))

    return AgentValidationResult(valid=not errors, errors=errors, warnings=warnings)


async def ensure_valid(payload: AgentCreate) -> None:
    result = await validate_agent(payload)
    if not result.valid:
        messages = "; ".join(issue.message for issue in result.errors)
        raise ValueError(messages)


async def validate_runtime_resources(agent: AgentCreate) -> list[ValidationIssue]:
    """保存时不做网络探测；显式点「校验」时才确认 MCP 工具真的存在。"""
    issues: list[ValidationIssue] = []
    for index, res in enumerate(agent.resources):
        if res.kind != "mcp":
            continue
        try:
            server = await mcp_repo.get_server(res.id)
            tools, _ = await mcp_client.probe_tools(server)
        except (mcp_repo.MCPServerNotFound, mcp_client.MCPError) as exc:
            issues.append(_issue(f"resources[{index}]", str(exc)))
            continue
        names = {item.name for item in tools}
        missing = [name for name in res.tools if name not in names]
        if missing:
            issues.append(
                _issue(f"resources[{index}]", f"MCP Server「{server.name}」缺少工具: {missing}")
            )
    return issues


def _empty_default(var_type: str) -> Any:
    if var_type == "number":
        return 0
    if var_type == "boolean":
        return False
    if var_type == "json":
        return {}
    return ""


def normalize_variables(agent: AgentCreate, variables: dict[str, Any]) -> dict[str, Any]:
    """合并默认值并做类型转换；必选缺失抛 ValueError。"""
    merged: dict[str, Any] = {}
    for var in agent.variables:
        if var.key in variables and variables[var.key] is not None:
            value = variables[var.key]
        elif not var.required:
            value = (
                var.default
                if var.default is not None and var.default != ""
                else _empty_default(var.type)
            )
        else:
            raise ValueError(f"必选变量 {var.key} 没有提供")
        merged[var.key] = _coerce(value, var.type, var.key)
    return merged


def coerce_value(value: Any, var_type: str, key: str) -> Any:
    """供 Flow start 变量复用同一套类型转换。"""
    return _coerce(value, var_type, key)


def _coerce(value: Any, var_type: str, key: str) -> Any:
    try:
        if var_type == "string":
            return value if isinstance(value, str) else str(value)
        if var_type == "number":
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            return int(number) if number.is_integer() else number
        if var_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    return True
                if value.lower() in ("false", "0", "no", ""):
                    return False
            if isinstance(value, (int, float)):
                return bool(value)
            raise ValueError
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, (dict, list)):
            return value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"变量 {key} 不能转换成 {var_type}: {value!r}") from exc
    raise ValueError(f"变量 {key} 不能转换成 {var_type}: {value!r}")
