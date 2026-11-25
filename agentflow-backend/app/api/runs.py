"""运行详情、历史、SSE 事件流与人工审批桩。"""
import asyncio
import uuid

import orjson
from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models.run import Run, RunEvent, RunStatus
from app.services.event_bus import event_bus, utc_now

router = APIRouter(prefix="/runs", tags=["runs"])


def _row_to_run(row) -> Run:
    return Run(
        id=row["id"],
        flow_id=row["flow_id"],
        flow_version=row["flow_version"],
        status=RunStatus(row["status"]),
        inputs=orjson.loads(row["inputs_json"]),
        outputs=orjson.loads(row["outputs_json"]) if row["outputs_json"] else None,
        state=orjson.loads(row["state_json"] or "{}"),
        error=row["error"],
        token_usage=row["token_usage"],
        cost_estimate=row["cost"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def _load_run(run_id: str) -> Run:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"运行不存在: {run_id}")
    return _row_to_run(row)


async def _update_status(run_id: str, status: RunStatus, error: str | None = None) -> Run:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
            (status.value, error, utc_now(), run_id),
        )
        await db.commit()
    finally:
        await db.close()
    return await _load_run(run_id)


@router.get("", response_model=list[Run])
async def list_runs(status: str | None = Query(default=None)):
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY started_at DESC", (status,)
            )
        else:
            cursor = await db.execute("SELECT * FROM runs ORDER BY started_at DESC")
        rows = await cursor.fetchall()
    finally:
        await db.close()
    return [_row_to_run(row) for row in rows]


@router.get("/{run_id}", response_model=Run)
async def get_run(run_id: str):
    return await _load_run(run_id)


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    """SSE：先补发 Last-Event-ID 之后的历史事件，再跟随实时队列。"""
    await _load_run(run_id)  # 不存在直接 404，避免建立一个永不结束的流

    header = request.headers.get("last-event-id")
    after_seq = int(header) if header and header.isdigit() else 0

    async def generator():
        queue = await event_bus.register(run_id)
        cursor_seq = after_seq
        try:
            for event in await event_bus.history(run_id, after_seq):
                cursor_seq = max(cursor_seq, event.seq)
                yield _serialize(event)
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"comment": "keep-alive"}
                    continue
                if event.seq > cursor_seq:
                    cursor_seq = event.seq
                    yield _serialize(event)
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


@router.post("/{run_id}/cancel", response_model=Run)
async def cancel_run(run_id: str):
    run = await _load_run(run_id)
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        return run
    updated = await _update_status(run_id, RunStatus.CANCELLED, "用户取消")
    await event_bus.emit(run_id, "run_failed", payload={"error": "用户取消", "cancelled": True})
    return updated


@router.post("/{run_id}/resume", response_model=Run)
async def resume_run(run_id: str, payload: dict | None = None):
    """P4 将从 checkpointer 快照真正续跑；P1 只恢复状态，保证交互链路可联调。"""
    run = await _load_run(run_id)
    if run.status != RunStatus.WAITING_HUMAN:
        raise HTTPException(status_code=409, detail="只有 waiting_human 状态的运行可以续跑")
    approved = (payload or {}).get("approved", True)
    if not approved:
        return await cancel_run(run_id)
    await event_bus.emit(run_id, "node_completed", payload={"approved": True})
    return await _update_status(run_id, RunStatus.RUNNING)


@router.post("/{run_id}/to-case")
async def run_to_case(run_id: str, payload: dict | None = None):
    """失败 Run 一键转 Case：从真实失败中生长评测集（P4 的前置数据通路）。"""
    run = await _load_run(run_id)
    events = await event_bus.history(run_id)
    used_tools = sorted({
        e.payload.get("name", "") for e in events if e.type == "tool_call" and e.payload.get("name")
    })
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
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM eval_sets WHERE id = ?", (set_id,))
        row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO eval_sets (id, name, cases_json, rubric_version, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (set_id, "默认评测集", "[]", "v1", utc_now()),
            )
        cursor = await db.execute("SELECT cases_json FROM eval_sets WHERE id = ?", (set_id,))
        cases = orjson.loads((await cursor.fetchone())["cases_json"])
        cases.append(case)
        await db.execute(
            "UPDATE eval_sets SET cases_json = ? WHERE id = ?",
            (orjson.dumps(cases).decode(), set_id),
        )
        await db.commit()
    finally:
        await db.close()
    return {"case_id": case["id"], "eval_set_id": set_id}
