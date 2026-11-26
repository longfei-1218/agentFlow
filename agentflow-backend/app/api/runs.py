"""运行详情、历史、SSE 事件流、取消/续跑与失败转 Case。"""
import asyncio
import uuid

import orjson
from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.database import db
from app.engine.demo_runner import run_demo_flow
from app.models.run import Run, RunEvent, RunStatus
from app.services.event_bus import event_bus, utc_now
from app.services.flow_repo import load_flow
from app.services.run_manager import run_manager
from app.services.run_repo import (
    TERMINAL_STATUSES,
    load_run,
    max_seq,
    row_to_run,
    update_run,
)

router = APIRouter(prefix="/runs", tags=["runs"])

_TERMINAL_EVENTS = {"run_completed", "run_failed"}


@router.get("", response_model=list[Run])
async def list_runs(
    flow_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    started_after: str | None = Query(default=None, description="ISO 时间下界（含）"),
    started_before: str | None = Query(default=None, description="ISO 时间上界（含）"),
    limit: int = Query(default=100, ge=1, le=500),
):
    where: list[str] = []
    params: list = []
    if flow_id:
        where.append("flow_id = ?")
        params.append(flow_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if started_after:
        where.append("started_at >= ?")
        params.append(started_after)
    if started_before:
        where.append("started_at <= ?")
        params.append(started_before)

    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    rows = await db.fetchall(sql, params)
    return [row_to_run(row) for row in rows]


@router.get("/{run_id}", response_model=Run)
async def get_run(run_id: str):
    return await load_run(run_id)


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    """SSE：先补发 Last-Event-ID 之后的历史事件，再跟随实时队列。

    run 已终态时补完历史即关闭，否则每次点开一条历史记录都会挂一个永不结束的连接。
    """
    run = await load_run(run_id)

    header = request.headers.get("last-event-id")
    after_seq = int(header) if header and header.isdigit() else 0

    async def generator():
        cursor_seq = after_seq
        history = await event_bus.history(run_id, after_seq)
        for event in history:
            cursor_seq = max(cursor_seq, event.seq)
            yield _serialize(event)
            if event.type in _TERMINAL_EVENTS:
                return
        if run.status in TERMINAL_STATUSES:
            return

        queue = await event_bus.register(run_id)
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"comment": "keep-alive"}
                    continue
                if event.seq <= cursor_seq:
                    continue
                cursor_seq = event.seq
                yield _serialize(event)
                if event.type in _TERMINAL_EVENTS:
                    return
        finally:
            event_bus.unregister(run_id, queue)

    return EventSourceResponse(
        generator(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _serialize(event: RunEvent) -> dict:
    return {
        "event": event.type,
        "id": str(event.seq),
        "data": orjson.dumps(event.model_dump(by_alias=True, mode="json")).decode(),
    }


@router.get("/{run_id}/stats")
async def run_stats(run_id: str):
    """节点维度聚合：耗时 / token / 成本，供前端运行回放与评测明细使用。"""
    await load_run(run_id)
    events = await event_bus.history(run_id)

    nodes: dict[str, dict] = {}
    open_at: dict[str, str] = {}
    for event in events:
        if not event.node_id:
            continue
        node = nodes.setdefault(
            event.node_id,
            {"nodeId": event.node_id, "tokens": 0, "cost": 0.0, "durationMs": 0, "status": "unknown"},
        )
        if event.type == "node_started":
            open_at[event.node_id] = event.created_at
            node["status"] = "running"
        elif event.type == "node_completed":
            started = open_at.pop(event.node_id, None)
            if started:
                node["durationMs"] = _duration_ms(started, event.created_at)
            node["status"] = "done"
        elif event.type == "token":
            node["tokens"] += int(event.payload.get("deltaTokens", 0))
            node["cost"] += float(event.payload.get("cost", 0.0))
        elif event.type == "tool_call":
            node["status"] = "running"
        elif event.type == "human_required":
            node["status"] = "waiting_human"
        elif event.type == "run_failed":
            node["status"] = "error"

    total_tokens = sum(node["tokens"] for node in nodes.values())
    return {
        "runId": run_id,
        "totalTokens": total_tokens,
        "nodes": list(nodes.values()),
    }


def _duration_ms(start: str, end: str) -> int:
    from datetime import datetime

    try:
        return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    except ValueError:
        return 0


@router.post("/{run_id}/cancel", response_model=Run)
async def cancel_run(run_id: str):
    run = await load_run(run_id)
    if run.status in TERMINAL_STATUSES:
        return run

    run_manager.request_cancel(run_id)
    if run_manager.is_active(run_id):
        # 取消是协作式的：等执行器自己写终态，避免两边同时改状态
        await run_manager.wait(run_id, timeout=3.0)
        return await load_run(run_id)

    # 没有活跃任务（比如服务重启后遗留的 run）：由 API 直接收尾
    await event_bus.emit(run_id, "run_failed", payload={"error": "用户取消", "cancelled": True})
    await update_run(
        run_id, status=RunStatus.CANCELLED.value, error="用户取消", finished_at=utc_now()
    )
    return await load_run(run_id)


@router.post("/{run_id}/resume", response_model=Run)
async def resume_run(run_id: str, payload: dict | None = None):
    """人工审批后从 state 快照续跑（LangGraph 阶段换成 checkpointer 恢复）。"""
    run = await load_run(run_id)
    if run.status != RunStatus.WAITING_HUMAN:
        raise HTTPException(status_code=409, detail="只有 waiting_human 状态的运行可以续跑")

    approved = (payload or {}).get("approved", True)
    if not approved:
        return await cancel_run(run_id)

    flow = await load_flow(run.flow_id)
    await update_run(run_id, status=RunStatus.RUNNING.value, error=None, finished_at=None)
    event_bus.seed_seq(run_id, await max_seq(run_id))
    stop = run_manager.cancel_token(run_id)
    run_manager.launch(run_id, run_demo_flow(run_id, flow, {}, stop=stop, resume_from=run.state))
    return await load_run(run_id)


@router.post("/{run_id}/to-case")
async def run_to_case(run_id: str, payload: dict | None = None):
    """失败 Run 一键转 Case：评测集从真实失败里生长，而不是凭空编题。"""
    run = await load_run(run_id)
    events = await event_bus.history(run_id)
    used_tools = sorted(
        {
            event.payload.get("name", "")
            for event in events
            if event.type == "tool_call" and event.payload.get("name")
        }
    )
    case = {
        "id": f"case_{uuid.uuid4().hex[:8]}",
        "input": run.inputs,
        "expected_outcome": None,
        "required_tools": used_tools,
        "forbidden_tools": [],
        "rubric": "",
        "source_run_id": run.id,
    }
    set_id = (payload or {}).get("eval_set_id") or "eval_default"

    row = await db.fetchone("SELECT id FROM eval_sets WHERE id = ?", (set_id,))
    if row is None:
        await db.execute(
            "INSERT INTO eval_sets (id, name, cases_json, rubric_version, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (set_id, "默认评测集", "[]", "v1", utc_now()),
        )
    row = await db.fetchone("SELECT cases_json FROM eval_sets WHERE id = ?", (set_id,))
    cases = orjson.loads(row["cases_json"]) if row and row["cases_json"] else []
    cases.append(case)
    await db.execute(
        "UPDATE eval_sets SET cases_json = ? WHERE id = ?",
        (orjson.dumps(cases).decode(), set_id),
    )
    return {"case_id": case["id"], "eval_set_id": set_id}
