"""Flow v2 校验：start/agent/condition/loop/human/end。

结构校验同步、无 DB；`validate_flow_runtime` 额外查 Agent 是否存在、
必选变量是否被 inputMap 覆盖、inputMap 路径是否指向已存在的节点。
"""
from collections import deque
from typing import Any

from app.models.flow import Flow, ValidationIssue, ValidationResult
from app.nodes.registry import validate_config
from app.services import agent_repo
from app.services.flow_vars import extract_paths


def _cfg(config: dict[str, Any], snake: str, camel: str, default: Any = None) -> Any:
    if snake in config:
        return config.get(snake)
    return config.get(camel, default)


def _issue(node_id: str | None, message: str) -> ValidationIssue:
    return ValidationIssue(node_id=node_id, message=message)


def validate_flow(flow: Flow) -> ValidationResult:
    errors: list[ValidationIssue] = []

    if flow.dsl_version != 2:
        return ValidationResult(
            valid=False,
            errors=[_issue(None, "旧 DSL 流程（dslVersion != 2）不支持编辑/运行，请新建 v2 流程")],
        )

    for node in flow.nodes:
        for problem in validate_config(node.type, node.config):
            errors.append(_issue(node.id, problem))

    ids = [node.id for node in flow.nodes]
    id_set = set(ids)
    if len(ids) != len(id_set):
        errors.append(_issue(None, "节点 ID 重复"))

    starts = [node for node in flow.nodes if node.type == "start"]
    ends = [node for node in flow.nodes if node.type == "end"]
    if len(starts) != 1:
        errors.append(_issue(None, "必须有且仅有一个 start 入口节点"))
    if len(ends) != 1:
        errors.append(_issue(None, "必须有且仅有一个 end 出口节点"))

    if starts:
        keys: set[str] = set()
        for index, var in enumerate(starts[0].config.get("variables") or []):
            key = str(var.get("key") or "")
            if key in keys:
                errors.append(_issue(starts[0].id, f"start 变量 key 重复: {key}"))
            keys.add(key)

    for edge in flow.edges:
        if edge.source not in id_set or edge.target not in id_set:
            errors.append(_issue(None, f"连线 {edge.id} 引用了不存在的节点"))
        if edge.source == edge.target:
            errors.append(_issue(edge.source, "节点不能连到自己"))

    linked = {edge.source for edge in flow.edges} | {edge.target for edge in flow.edges}
    for node in flow.nodes:
        if node.id not in linked:
            errors.append(_issue(node.id, "孤立节点：未连接任何边"))

    for node in flow.nodes:
        if node.type != "condition":
            continue
        handles = {edge.source_handle for edge in flow.edges if edge.source == node.id}
        if not {"true", "false"} <= handles:
            errors.append(_issue(node.id, "condition 的 true/false 分支必须都连线"))

    for node in flow.nodes:
        if node.type != "loop":
            continue
        handles = {edge.source_handle for edge in flow.edges if edge.source == node.id}
        if "body" not in handles:
            errors.append(_issue(node.id, "loop 节点必须有一条 body 分支连线"))

    # 环检测：回到 loop 节点的边是合法回边，不参与入度
    indegree = {node.id: 0 for node in flow.nodes}
    adjacency: dict[str, list[str]] = {node.id: [] for node in flow.nodes}
    loop_ids = {node.id for node in flow.nodes if node.type == "loop"}
    for edge in flow.edges:
        if edge.target in loop_ids:
            continue
        indegree[edge.target] += 1
        adjacency[edge.source].append(edge.target)

    queue = deque([node_id for node_id, degree in indegree.items() if degree == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(flow.nodes):
        errors.append(_issue(None, "流程中存在环（loop 回边除外）"))

    return ValidationResult(valid=not errors, errors=errors)


async def validate_flow_runtime(flow: Flow) -> ValidationResult:
    result = validate_flow(flow)
    if not result.valid:
        return result

    start = next(node for node in flow.nodes if node.type == "start")
    start_keys = {
        str(item.get("key")) for item in (start.config.get("variables") or [])
    }
    nodes = {node.id: node for node in flow.nodes}
    errors: list[ValidationIssue] = []

    for node in flow.nodes:
        if node.type != "agent":
            continue
        config = node.config or {}
        agent_id = str(_cfg(config, "agent_id", "agentId", "") or "")
        try:
            agent = await agent_repo.get_agent(agent_id)
        except agent_repo.AgentNotFound:
            errors.append(_issue(node.id, f"引用的 Agent 不存在: {agent_id}"))
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(_issue(node.id, f"读取 Agent 失败: {exc}"))
            continue

        input_map = _cfg(config, "input_map", "inputMap", {}) or {}
        if not isinstance(input_map, dict):
            errors.append(_issue(node.id, "inputMap 必须是对象"))
            continue
        agent_keys = {var.key for var in agent.variables}
        for key in input_map:
            if key not in agent_keys:
                errors.append(_issue(node.id, f"inputMap 的键 {key} 不是 Agent 变量"))

        for var in agent.variables:
            if not var.required:
                continue
            mapped = input_map.get(var.key)
            if not isinstance(mapped, str) or not mapped.strip():
                errors.append(
                    _issue(node.id, f"Agent 必选变量 {var.key} 没有映射")
                )

        for key, template in input_map.items():
            if not isinstance(template, str):
                errors.append(_issue(node.id, f"inputMap.{key} 必须是模板字符串"))
                continue
            for path in extract_paths(template):
                parts = path.split(".")
                if parts[0] == "start":
                    if len(parts) != 2 or parts[1] not in start_keys:
                        errors.append(
                            _issue(node.id, f"inputMap.{key} 引用了不存在的输入: {{{{path}}}}")
                        )
                elif parts[0] in nodes:
                    if len(parts) < 2 or parts[1] != "output":
                        errors.append(
                            _issue(node.id, f"inputMap.{key} 只能引用上游的 output: {{{{path}}}}")
                        )
                elif len(parts) >= 2:
                    errors.append(
                        _issue(node.id, f"inputMap.{key} 引用了不存在的节点: {{{{path}}}}")
                    )

    return ValidationResult(valid=not errors, errors=errors)
