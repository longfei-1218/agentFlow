"""执行引擎公共件：拓扑排序、状态快照、可取消的等待、终态收尾。

demo_runner（确定性演示）与 loop（真实 Agent Loop）共用这一套，
避免两份执行器各自实现一遍导致行为漂移。
"""
import asyncio

import orjson

from app.models.flow import Flow
from app.models.run import RunStatus
from app.services.event_bus import event_bus, utc_now
from app.services.run_repo import update_run

DEFAULT_STATE = {
    "cursor": 0,
    "variables": {},
    "tokens": 0,          # 累计 token（含输入+输出）
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "cost": 0.0,          # 元（人民币），按 provider 返回的用量折算
    "steps": 0,           # 已发生的 LLM 调用次数，用于 MAX_STEPS 守卫
    "human_pending": None,
    "current_node": None,
    "model": None,
    "tool_calls": [],     # R3：本次 run 里真实执行过的工具调用摘要
    "tool_errors": [],    # R3：FC 里回给模型的工具错误（不致命，但要留痕）
    "outputs": {},        # R4：output 节点产出的字段（图执行器直接写在 state 里）
    "branch": {},         # R4：condition / loop 节点本轮走的分支，条件边据此路由
    "loop_rounds": {},    # R4：每个 loop 节点已经跑了第几轮
}

# 节点在 node_started 事件里露出的摘要字段：让界面显示「模型/温度」而不是整坨 config
NODE_SUMMARY_KEYS = {
    "llm": ["model", "temperature", "max_tokens", "tool_ids"],
    "prompt": ["template"],
    "input": ["name", "type"],
    "output": ["fields"],
    "tool": ["tool_id", "args_template"],
    "mcp": ["server_id", "tool_name"],
    "knowledge": ["kb_id", "top_k", "rerank"],
    "condition": ["expression"],
    "loop": ["max_rounds", "exit_condition"],
    "human": ["message"],
    "skill": ["flow_id"],
}


def topological_order(flow: Flow) -> list[str]:
    """Kahn 拓扑序；有环时把剩余节点补在末尾，执行器不能因此卡死。"""
    indegree = {node.id: 0 for node in flow.nodes}
    adjacency: dict[str, list[str]] = {node.id: [] for node in flow.nodes}
    for edge in flow.edges:
        if edge.source in adjacency and edge.target in indegree:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    order.extend(node_id for node_id in indegree if node_id not in order)
    return order


def node_summary(node_type: str, config: dict) -> dict:
    return {
        key: config[key]
        for key in NODE_SUMMARY_KEYS.get(node_type, [])
        if key in config
    }


async def pause(stop: asyncio.Event, delay: float) -> None:
    """可被取消令牌提前唤醒的 sleep。"""
    if delay <= 0:
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except asyncio.TimeoutError:
        pass


def dump_state(state: dict) -> str:
    return orjson.dumps(state).decode()


async def write_state(run_id: str, state: dict) -> None:
    await update_run(
        run_id,
        state_json=dump_state(state),
        token_usage=state["tokens"],
        cost=round(state["cost"], 6),
    )


async def finish_cancelled(run_id: str, state: dict) -> None:
    await event_bus.emit(run_id, "run_failed", payload={"error": "用户取消", "cancelled": True})
    await update_run(
        run_id,
        status=RunStatus.CANCELLED.value,
        error="用户取消",
        state_json=dump_state(state),
        finished_at=utc_now(),
    )
