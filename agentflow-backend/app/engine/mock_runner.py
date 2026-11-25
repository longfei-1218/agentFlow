"""P1 演示执行器：用确定性的事件序列打通「运行 -> SSE -> 前端日志」通路。

P2 会用 app/engine/loop.py 的手写 Agent Loop 替换本文件；
此文件保留为 SSE 联调与前端开发桩，不调用真实 LLM。
"""
import asyncio
from collections import deque

import orjson

from app.database import get_db
from app.models.flow import Flow
from app.models.run import RunStatus
from app.services.event_bus import event_bus, utc_now

_DEFAULT_ANSWER = "已收到你的问题。当前是 P1 演示执行器：事件由本地桩生成，P2 将接入真实 LLM。"


def _topological_order(flow: Flow) -> list[str]:
    indegree = {n.id: 0 for n in flow.nodes}
    adjacency: dict[str, list[str]] = {n.id: [] for n in flow.nodes}
    for edge in flow.edges:
        if edge.source in adjacency and edge.target in indegree:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

    queue = deque([nid for nid, deg in indegree.items() if deg == 0])
    result: list[str] = []
    while queue:
        current = queue.popleft()
        result.append(current)
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    # 有环时把剩余节点追加，避免演示执行器卡死
    result.extend(nid for nid in indegree if nid not in result)
    return result


def _node_summary(node_type: str, config: dict) -> dict:
    keys = {
        "llm": ["model", "temperature", "max_tokens"],
        "prompt": ["template"],
        "input": ["name", "type"],
        "output": ["fields"],
        "tool": ["tool_id", "timeout"],
        "mcp": ["server_id", "tool_name"],
        "knowledge": ["kb_id", "top_k", "rerank"],
        "condition": ["expression"],
        "loop": ["max_rounds"],
        "human": ["message"],
        "skill": ["flow_id"],
    }.get(node_type, [])
    return {k: config[k] for k in keys if k in config}


async def _update_run(run_id: str, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db = await get_db()
    try:
        await db.execute(
            f"UPDATE runs SET {assignments} WHERE id = ?",
            [*fields.values(), run_id],
        )
        await db.commit()
    finally:
        await db.close()


async def run_mock_flow(run_id: str, flow: Flow, inputs: dict) -> None:
    """按拓扑顺序逐节点发事件，最后写入 succeeded 与最终输出。"""
    try:
        await event_bus.emit(run_id, "run_started", payload={"inputs": inputs})
        await _update_run(run_id, status=RunStatus.RUNNING.value, started_at=utc_now())

        node_map = {n.id: n for n in flow.nodes}
        for node_id in _topological_order(flow):
            node = node_map.get(node_id)
            if node is None:
                continue
            await event_bus.emit(
                run_id, "node_started", node_id, _node_summary(node.type, node.config)
            )
            await asyncio.sleep(0.05)

            if node.type == "llm":
                for chunk in ("你好，", "这是 ", "流式 ", "token ", "输出。"):
                    await event_bus.emit(
                        run_id,
                        "token",
                        node_id,
                        {"text": chunk, "deltaTokens": 2},
                    )
                    await asyncio.sleep(0.03)
            elif node.type == "tool":
                await event_bus.emit(
                    run_id, "tool_call", node_id,
                    {"name": node.config.get("tool_id", "demo_tool"), "args": inputs},
                )
                await event_bus.emit(
                    run_id, "tool_result", node_id, {"result": "演示工具返回结果"}
                )
            elif node.type == "human":
                await event_bus.emit(
                    run_id, "human_required", node_id,
                    {"message": node.config.get("message", "是否继续执行？"), "timeout_s": 300},
                )
                await _update_run(run_id, status=RunStatus.WAITING_HUMAN.value)
                return  # P4 的 /resume 会负责续跑

            await event_bus.emit(run_id, "node_completed", node_id, {"ok": True})

        outputs = {"answer": _DEFAULT_ANSWER}
        await event_bus.emit(
            run_id, "run_completed", payload={"outputs": outputs, "tokens": 10, "cost": 0.0001}
        )
        await _update_run(
            run_id,
            status=RunStatus.SUCCEEDED.value,
            outputs_json=orjson.dumps(outputs).decode(),
            token_usage=10,
            cost=0.0001,
            finished_at=utc_now(),
        )
    except Exception as exc:  # noqa: BLE001 - 引擎异常必须转为事件，不能冲掉后台任务
        message = f"{type(exc).__name__}: {exc}"
        await event_bus.emit(run_id, "run_failed", payload={"error": message})
        await _update_run(
            run_id, status=RunStatus.FAILED.value, error=message, finished_at=utc_now()
        )
