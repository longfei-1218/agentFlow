"""Flow CRUD / 校验 / 触发执行。API 层不含编排逻辑。"""
import uuid
from datetime import datetime, timezone

import orjson
from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.database import db
from app.engine.demo_runner import run_demo_flow
from app.models.flow import Flow, FlowCreate, FlowEdge, FlowNode
from app.models.run import Run, RunStatus
from app.services.event_bus import event_bus, utc_now
from app.services.flow_repo import load_flow, row_to_flow, save_flow
from app.services.flow_service import validate_flow
from app.services.run_manager import run_manager
from app.services.run_repo import max_seq

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


def _invalid_flow_response(errors) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "FLOW_INVALID",
            "message": "流程校验未通过，无法执行",
            "detail": [issue.model_dump(by_alias=True) for issue in errors],
        },
    )


@router.get("", response_model=list[Flow])
async def list_flows():
    rows = await db.fetchall("SELECT dsl_json FROM flows ORDER BY updated_at DESC")
    return [row_to_flow(row) for row in rows]


@router.post("", response_model=Flow, status_code=status.HTTP_201_CREATED)
async def create_flow(payload: FlowCreate):
    """未传 nodes 时生成默认三节点流程；显式传空数组则尊重调用方意图（建空白画布）。"""
    now = _now()
    nodes = payload.nodes if payload.nodes is not None else [
        FlowNode.model_validate(node) for node in _DEFAULT_FLOW["nodes"]
    ]
    edges = payload.edges if payload.edges is not None else [
        FlowEdge.model_validate(edge) for edge in _DEFAULT_FLOW["edges"]
    ]
    # 空列表也视为「调用方明确没给结构」，只有 None 才走默认值；见 tests/test_flows.py
    flow = Flow(
        id=f"flow_{uuid.uuid4().hex[:8]}",
        name=payload.name,
        version=1,
        nodes=nodes,
        edges=edges,
        created_at=now,
        updated_at=now,
    )
    await db.execute(
        "INSERT INTO flows (id, name, version, dsl_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            flow.id,
            flow.name,
            flow.version,
            orjson.dumps(flow.model_dump()).decode(),
            now,
            now,
        ),
    )
    return flow


@router.get("/{flow_id}", response_model=Flow)
async def get_flow(flow_id: str):
    return await load_flow(flow_id)


@router.put("/{flow_id}", response_model=Flow)
async def update_flow(flow_id: str, payload: FlowCreate):
    """草稿保存：只更新内容，version 不变。

    version 的语义是「发布版本」，前端自动保存如果每次都 +1，
    编辑十分钟就能涨到几十上百，P4 的按版本对比会直接失真。
    """
    existing = await load_flow(flow_id)
    flow = Flow(
        id=flow_id,
        name=payload.name,
        version=existing.version,
        nodes=payload.nodes if payload.nodes is not None else existing.nodes,
        edges=payload.edges if payload.edges is not None else existing.edges,
        created_at=existing.created_at,
        updated_at=_now(),
    )
    return await save_flow(flow)


@router.post("/{flow_id}/publish", response_model=Flow)
async def publish_flow(flow_id: str):
    """显式发布：version + 1，评测按此版本做回归对比。"""
    existing = await load_flow(flow_id)
    result = validate_flow(existing)
    if not result.valid:
        return _invalid_flow_response(result.errors)
    flow = existing.model_copy(update={"updated_at": _now()})
    return await save_flow(flow, bump_version=True)


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(flow_id: str):
    deleted = await db.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{flow_id}/validate")
async def validate_flow_endpoint(flow_id: str):
    return validate_flow(await load_flow(flow_id))


@router.post("/{flow_id}/run", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def start_run(flow_id: str, payload: dict | None = None):
    flow = await load_flow(flow_id)

    result = validate_flow(flow)
    if not result.valid:
        return _invalid_flow_response(result.errors)

    inputs = (payload or {}).get("inputs", {}) if payload else {}
    run = Run(
        id=f"run_{uuid.uuid4().hex[:8]}",
        flow_id=flow_id,
        flow_version=flow.version,
        status=RunStatus.PENDING,
        inputs=inputs,
        started_at=utc_now(),
    )
    await db.execute(
        "INSERT INTO runs (id, flow_id, flow_version, status, inputs_json, state_json, "
        "token_usage, cost, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.id,
            flow_id,
            flow.version,
            run.status.value,
            orjson.dumps(inputs).decode(),
            "{}",
            0,
            0.0,
            run.started_at,
        ),
    )

    # 重启后同名 run 的 seq 必须接着库里最大序号走
    event_bus.seed_seq(run.id, await max_seq(run.id))
    stop = run_manager.cancel_token(run.id)
    run_manager.launch(run.id, run_demo_flow(run.id, flow, inputs, stop=stop))
    return run
