"""Flow 业务校验与设计稿对齐的辅助函数。

校验内容：唯一入口/出口、孤立节点、环检测（Kahn 拓扑排序）、condition 双分支。
注意：loop 节点的回边不参与环检测，否则合法循环会被误判。
"""
from collections import deque

from app.models.flow import Flow, ValidationIssue, ValidationResult


def validate_flow(flow: Flow) -> ValidationResult:
    errors: list[ValidationIssue] = []
    ids = [n.id for n in flow.nodes]
    id_set = set(ids)

    if len(ids) != len(id_set):
        errors.append(ValidationIssue(message="节点 ID 重复"))

    inputs = [n for n in flow.nodes if n.type == "input"]
    outputs = [n for n in flow.nodes if n.type == "output"]
    if len(inputs) != 1:
        errors.append(ValidationIssue(message="必须有且仅有一个 input 入口节点"))
    if len(outputs) != 1:
        errors.append(ValidationIssue(message="必须有且仅有一个 output 出口节点"))

    for edge in flow.edges:
        if edge.source not in id_set or edge.target not in id_set:
            errors.append(ValidationIssue(message=f"连线 {edge.id} 引用了不存在的节点"))
        if edge.source == edge.target:
            errors.append(ValidationIssue(node_id=edge.source, message="节点不能连到自己"))

    linked = {e.source for e in flow.edges} | {e.target for e in flow.edges}
    for node in flow.nodes:
        if node.id not in linked:
            errors.append(ValidationIssue(node_id=node.id, message="孤立节点：未连接任何边"))

    # condition 节点必须连出 true / false 两条分支
    for node in flow.nodes:
        if node.type != "condition":
            continue
        handles = {e.source_handle for e in flow.edges if e.source == node.id}
        if not {"true", "false"} <= handles:
            errors.append(
                ValidationIssue(node_id=node.id, message="condition 的 true/false 分支必须都连线")
            )

    # 环检测：排除 loop 节点发出的回边
    indegree = {n.id: 0 for n in flow.nodes}
    adjacency: dict[str, list[str]] = {n.id: [] for n in flow.nodes}
    loop_ids = {n.id for n in flow.nodes if n.type == "loop"}
    for edge in flow.edges:
        if edge.source in loop_ids and edge.target in loop_ids:
            continue
        indegree[edge.target] += 1
        adjacency[edge.source].append(edge.target)

    queue = deque([nid for nid, deg in indegree.items() if deg == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(flow.nodes):
        errors.append(ValidationIssue(message="流程中存在环（loop 回边除外）"))

    return ValidationResult(valid=not errors, errors=errors)
