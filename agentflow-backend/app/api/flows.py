"""Flow CRUD / 校验 / 触发执行。API 层不含编排逻辑。"""
import asyncio
import uuid
from datetime import datetime, timezone

import orjson
from fastapi import APIRouter, HTTPException, Response, status

from app.database import get_db
from app.engine.mock_runner import run_mock_flow
from app.models.flow import Flow, FlowCreate, FlowEdge, FlowNode, ValidationResult
from app.models.run import Run, RunStatus
from app.services.event_bus import event_bus, utc_now
from app.services.flow_service import validate_flow

router = APIRouter(prefix="/flows", tags=["flows"])

_DEFAULT_FLOW = {
    "nodes": [
        {
            "id": "input_1",
            "type": "input",
            "position": {"x": 80, "y": 160},
            "config": {"name": "query", "type": "string", "default": ""},
        },
        {
            "id": "llm_1",
            "type": "llm",
            "position": {"x": 360, "y": 160},
            "config": {
                "model": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 1024,
                "system": "你是一个有帮助的助手。",
            },
        },
        {
            "id": "output_1",
            "type": "output",
            "position": {"x": 640, "y": 160},
            "config": {"fields": ["text"]},
        },
    ],
    "edges": [
        {"id": "e_1", "source": "input_1", "target": "llm_1"},
        {"id": "e_2", "source": "llm_1", "target": "output_1"},
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_flow(row) -> Flow:
    return Flow.model_validate(orjson.loads(row["dsl_json"]))


async def _load_flow(flow_id: str) -> Flow:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT dsl_json FROM flows WHERE id = ?", (flow_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    return _row_to_flow(row)


@router.get("", response_model=list[Flow])
async def list_flows():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT dsl_json FROM flows ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
    finally:
        await db.close()
    return [_row_to_flow(row) for row in rows]


@router.post("", response_model=Flow, status_code=status.HTTP_201_CREATED)
async def create_flow(payload: FlowCreate):
    now = _now()
    nodes = payload.nodes or [FlowNode.model_validate(n) for n in _DEFAULT_FLOW["nodes"]]
    edges = payload.edges or [FlowEdge.model_validate(e) for e in _DEFAULT_FLOW["edges"]]
    flow = Flow(
        id=f"flow_{uuid.uuid4().hex[:8]}",
        name=payload.name,
        version=1,
        nodes=nodes,
        edges=edges,
        created_at=now,
        updated_at=now,
    )
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO flows (id, name, version, dsl_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (flow.id, flow.name, flow.version, orjson.dumps(flow.model_dump()).decode(), now, now),
        )
        await db.commit()
    finally:
        await db.close()
    return flow


@router.get("/{flow_id}", response_model=Flow)
async def get_flow(flow_id: str):
    return await _load_flow(flow_id)


@router.put("/{flow_id}", response_model=Flow)
async def update_flow(flow_id: str, payload: FlowCreate):
    existing = await _load_flow(flow_id)
    now = _now()
    flow = Flow(
        id=flow_id,
        name=payload.name,
        version=existing.version + 1,
        nodes=payload.nodes,
        edges=payload.edges,
        created_at=existing.created_at,
        updated_at=now,
    )
    db = await get_db()
    try:
        await db.execute(
            "UPDATE flows SET name = ?, version = ?, dsl_json = ?, updated_at = ? WHERE id = ?",
            (flow.name, flow.version, orjson.dumps(flow.model_dump()).decode(), now, flow_id),
        )
        await db.commit()
    finally:
        await db.close()
    return flow


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(flow_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{flow_id}/validate", response_model=ValidationResult)
async def validate_flow_endpoint(flow_id: str):
    return validate_flow(await _load_flow(flow_id))


@router.post("/{flow_id}/run", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def start_run(flow_id: str, payload: dict | None = None):
    flow = await _load_flow(flow_id)
    inputs = (payload or {}).get("inputs", {}) if payload else {}
    run = Run(
        id=f"run_{uuid.uuid4().hex[:8]}",
        flow_id=flow_id,
        flow_version=flow.version,
        status=RunStatus.PENDING,
        inputs=inputs,
        started_at=utc_now(),
    )
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO runs (id, flow_id, flow_version, status, inputs_json, state_json, "
            "token_usage, cost, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id, flow_id, flow.version, run.status.value,
                orjson.dumps(inputs).decode(), "{}", 0, 0.0, run.started_at,
            ),
        )
        await db.commit()
    finally:
        await db.close()

    event_bus.seed_seq(run.id, 0)
    asyncio.create_task(run_mock_flow(run.id, flow, inputs))
    return run
