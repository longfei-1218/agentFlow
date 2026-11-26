"""确定性演示执行器（不调用 LLM）。

职责：在没有 LLM 的情况下验证「运行 -> SSE -> 取消 -> 人工审批 -> 断点续跑」整条链路，
它是真实 Agent Loop 的回归基准，也是前端联调时的稳定桩。

拓扑/状态/终态这些公共件已移到 app/engine/common.py，与 loop.py 共用。
"""
import asyncio

import orjson

from app.config import settings
from app.engine.common import (
    DEFAULT_STATE,
    dump_state as _dump,
    finish_cancelled as _finish_cancelled,
    node_summary,
    pause as _pause,
    topological_order,
    write_state as _write_state,
)
from app.models.flow import Flow
from app.models.run import RunStatus
from app.services.event_bus import event_bus, utc_now
from app.services.run_repo import load_run, update_run

DEMO_ANSWER = "已收到你的问题。当前是演示执行器：事件由本地桩生成，真实模型运行请把 RUNNER 设为 loop。"
DEMO_TOKENS = ("你好，", "这是 ", "流式 ", "token ", "输出。")
TOKEN_COST = 0.00001  # 演示单价：每个 token 一分不到，仅用于打通成本统计


async def run_demo_flow(
    run_id: str,
    flow: Flow,
    inputs: dict,
    *,
    stop: asyncio.Event,
    resume_from: dict | None = None,
) -> None:
    state = {**DEFAULT_STATE, **(resume_from or {})}
    state["variables"] = dict(state.get("variables") or {})
    order = topological_order(flow)
    node_map = {node.id: node for node in flow.nodes}
    delay = max(settings.DEMO_STEP_DELAY, 0.0)

    try:
        if state["cursor"] == 0:
            state["variables"] = {**state["variables"], **inputs}
            await update_run(
                run_id,
                status=RunStatus.RUNNING.value,
                started_at=utc_now(),
                state_json=_dump(state),
            )
            await event_bus.emit(run_id, "run_started", payload={"inputs": inputs})

        for index in range(state["cursor"], len(order)):
            if stop.is_set():
                await _finish_cancelled(run_id, state)
                return

            node = node_map.get(order[index])
            if node is None:
                state["cursor"] = index + 1
                continue

            # 审批通过后重入同一个 human 节点：不重复发 node_started，直接收尾
            resuming_human = node.type == "human" and state.get("human_pending") == node.id
            if not resuming_human:
                await event_bus.emit(
                    run_id, "node_started", node.id, node_summary(node.type, node.config)
                )
                state["current_node"] = node.id
                await _write_state(run_id, state)
                await _pause(stop, delay)
                if stop.is_set():
                    await _finish_cancelled(run_id, state)
                    return

            if node.type == "llm":
                for chunk in DEMO_TOKENS:
                    state["tokens"] += 2
                    state["cost"] += TOKEN_COST * 2
                    await event_bus.emit(
                        run_id, "token", node.id, {"text": chunk, "deltaTokens": 2}
                    )
                    await _pause(stop, delay * 0.6)
                    if stop.is_set():
                        await _finish_cancelled(run_id, state)
                        return
                state["variables"]["text"] = DEMO_ANSWER
            elif node.type == "tool":
                await event_bus.emit(
                    run_id,
                    "tool_call",
                    node.id,
                    {"name": node.config.get("tool_id", "demo_tool"), "args": state["variables"]},
                )
                await event_bus.emit(
                    run_id, "tool_result", node.id, {"result": "演示工具返回结果"}
                )
                state["variables"]["result"] = "演示工具返回结果"
            elif node.type == "prompt":
                template = str(node.config.get("template", ""))
                for key, value in state["variables"].items():
                    template = template.replace("{{" + key + "}}", str(value))
                state["variables"]["text"] = template
            elif node.type == "human":
                if not resuming_human:
                    state["cursor"] = index
                    state["human_pending"] = node.id
                    await _write_state(run_id, state)
                    await update_run(run_id, status=RunStatus.WAITING_HUMAN.value)
                    await event_bus.emit(
                        run_id,
                        "human_required",
                        node.id,
                        {
                            "message": node.config.get("message", "是否继续执行？"),
                            "timeout_s": node.config.get("timeout", 300),
                        },
                    )
                    return
                state["human_pending"] = None
                state["variables"]["approved"] = True

            state["cursor"] = index + 1
            state["current_node"] = None
            await _write_state(run_id, state)
            await event_bus.emit(run_id, "node_completed", node.id, {"ok": True})

        outputs = {"answer": state["variables"].get("text") or DEMO_ANSWER}
        if stop.is_set():
            await _finish_cancelled(run_id, state)
            return
        await event_bus.emit(
            run_id,
            "run_completed",
            payload={"outputs": outputs, "tokens": state["tokens"], "cost": round(state["cost"], 6)},
        )
        await update_run(
            run_id,
            status=RunStatus.SUCCEEDED.value,
            outputs_json=orjson.dumps(outputs).decode(),
            state_json=_dump(state),
            token_usage=state["tokens"],
            cost=round(state["cost"], 6),
            finished_at=utc_now(),
        )
    except asyncio.CancelledError:
        # 进程关闭或显式 cancel：也要留下可读的终态，不能只留 running
        await _finish_cancelled(run_id, state)
        raise
    except Exception as exc:  # noqa: BLE001 - 引擎异常必须转成事件，不能冲掉后台任务
        message = f"{type(exc).__name__}: {exc}"
        await event_bus.emit(run_id, "run_failed", payload={"error": message})
        await update_run(
            run_id,
            status=RunStatus.FAILED.value,
            error=message,
            state_json=_dump(state),
            finished_at=utc_now(),
        )


async def resume_demo_flow(run_id: str, flow: Flow, stop: asyncio.Event) -> None:
    """审批通过/失败重跑时从 state 快照续跑。"""
    run = await load_run(run_id)
    await run_demo_flow(run_id, flow, {}, stop=stop, resume_from=run.state)
