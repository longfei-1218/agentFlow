"""Flow CRUD / 校验 / 触发执行。API 层不含编排逻辑。"""
import uuid
from datetime import datetime, timezone

import orjson
from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.database import db
from app.engine import executor
from app.models.flow import Flow, FlowCreate, FlowEdge, FlowNode
from app.models.run import Run, RunStatus
from app.models.version import PublishRequest, PublishState, RollbackRequest, VersionDetail
from app.services import run_manifest, version_repo
from app.services.event_bus import event_bus, utc_now
from app.services.flow_repo import load_flow, row_to_flow, save_flow
from app.services.flow_service import validate_flow_runtime
from app.services.run_manager import run_manager
from app.services.run_repo import max_seq
from app.services.settings_repo import get_llm_config

router = APIRouter(prefix="/flows", tags=["flows"])

_DEFAULT_FLOW = {
    "nodes": [
        {
            "id": "start_1",
            "type": "start",
            "position": {"x": 80, "y": 160},
            "config": {
                "variables": [
                    {"key": "query", "label": "用户输入", "type": "string", "required": True}
                ]
            },
        },
        {
            "id": "end_1",
            "type": "end",
            "position": {"x": 360, "y": 160},
            "config": {"outputs": []},
        },
    ],
    "edges": [
        {"id": "e_1", "source": "start_1", "target": "end_1"},
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invalid_flow_response(errors) -> JSONResponse:
    if errors and errors[0].node_id is None and "旧 DSL" in errors[0].message:
        return _legacy_flow_response()
    return JSONResponse(
        status_code=422,
        content={
            "code": "FLOW_INVALID",
            "message": "流程校验未通过，无法执行",
            "detail": [issue.model_dump(by_alias=True) for issue in errors],
        },
    )


def _legacy_flow_response() -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "FLOW_DSL_LEGACY",
            "message": "该流程是旧 DSL（dslVersion != 2），不支持编辑、校验或运行；请新建 v2 流程",
            "detail": None,
        },
    )


@router.get("", response_model=list[Flow])
async def list_flows():
    rows = await db.fetchall("SELECT * FROM flows ORDER BY updated_at DESC")
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
        dsl_version=2,
        draft_hash=None,
        published_hash=None,
        nodes=nodes,
        edges=edges,
        created_at=now,
        updated_at=now,
    )
    draft_hash = version_repo.flow_config_hash(flow)
    flow = flow.model_copy(update={"draft_hash": draft_hash})
    await db.execute(
        "INSERT INTO flows (id, name, version, draft_hash, published_hash, dsl_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            flow.id,
            flow.name,
            flow.version,
            draft_hash,
            None,
            orjson.dumps(
                flow.model_dump(exclude={"draft_hash", "published_hash"})
            ).decode(),
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
    if existing.dsl_version != 2:
        return _legacy_flow_response()

    # 乐观锁：只有当调用方明确给出 baseUpdatedAt 时才校验（老调用/脚本不受影响）。
    # 没有这道闸，一个开着不动的旧标签页点「运行」会先 save() 把服务端改过的配置原地覆盖回去。
    if (
        payload.base_updated_at
        and existing.updated_at
        and payload.base_updated_at != existing.updated_at
    ):
        return JSONResponse(
            status_code=409,
            content={
                "code": "FLOW_STALE",
                "message": (
                    "该流程在别的窗口或标签页已被修改，本次保存没有覆盖服务端内容；"
                    "页面已重新加载最新版本，请确认后再操作"
                ),
                "detail": None,
            },
        )

    flow = Flow(
        id=flow_id,
        name=payload.name,
        version=existing.version,
        dsl_version=2,
        draft_hash=existing.draft_hash,
        published_hash=existing.published_hash,
        nodes=payload.nodes if payload.nodes is not None else existing.nodes,
        edges=payload.edges if payload.edges is not None else existing.edges,
        created_at=existing.created_at,
        updated_at=_now(),
    )
    return await save_flow(flow)


@router.post("/{flow_id}/publish", response_model=Flow)
async def publish_flow(flow_id: str, payload: PublishRequest | None = None):
    """发布 = 快照 + 配置指纹 + 绑定各节点 Agent 发布版本 + 代码 commit。

    回滚过的流程版本指针可能小于历史最大版本，发布层按 MAX+1 追加；
    不检查内容是否有改动，版本名必填、说明可留空。
    """
    existing = await load_flow(flow_id)
    if existing.dsl_version != 2:
        return _legacy_flow_response()

    name = (payload.name if payload else "").strip()
    if not name:
        return JSONResponse(
            status_code=422,
            content={"code": "VERSION_NAME_REQUIRED", "message": "发布前请填写版本名", "detail": None},
        )

    # 先按当前保存内容做结构校验，避免 Agent 绑定错误掩盖真正的编排错误
    current_check = await validate_flow_runtime(existing)
    if not current_check.valid:
        return _invalid_flow_response(current_check.errors)

    pins, pinned, missing = await run_manifest.resolve_flow_pins(existing)
    if missing:
        return JSONResponse(
            status_code=422,
            content={
                "code": "AGENT_VERSION_MISSING",
                "message": "发布前必须先发布这些 Agent 节点引用的 Agent",
                "detail": missing,
            },
        )

    # 关键：用「绑定的 Agent 发布快照」再校验一次 inputMap；
    # 草稿里改过变量而没发布 Agent 时，这里会拦住，避免发布一个跑不动的版本
    bound_check = await validate_flow_runtime(existing, agents_by_node=pinned)
    if not bound_check.valid:
        return _invalid_flow_response(bound_check.errors)

    await version_repo.publish_flow(
        existing,
        agent_refs=pins,
        pinned_agents=list(pinned.values()),
        name=name,
        note=((payload.note if payload else "") or "").strip(),
    )
    return await load_flow(flow_id)


@router.get("/{flow_id}/versions", response_model=list[VersionDetail])
async def list_flow_versions(flow_id: str):
    await load_flow(flow_id)
    return await version_repo.list_versions("flow", flow_id)


@router.get("/{flow_id}/versions/{version}", response_model=VersionDetail)
async def get_flow_version(flow_id: str, version: int):
    try:
        return await version_repo.get_version("flow", flow_id, version)
    except version_repo.VersionNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "VERSION_NOT_FOUND", "message": str(exc), "detail": None},
        )


@router.get("/{flow_id}/publish-state", response_model=PublishState)
async def get_flow_publish_state(flow_id: str):
    try:
        return await version_repo.publish_state("flow", flow_id)
    except version_repo.VersionNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "VERSION_NOT_FOUND", "message": str(exc), "detail": None},
        )


@router.post("/{flow_id}/rollback", response_model=Flow)
async def rollback_flow(flow_id: str, payload: RollbackRequest):
    """发布指针指回历史版本 + 该版本快照写回草稿；不改动任何 Agent 的版本。"""
    await load_flow(flow_id)
    try:
        await version_repo.rollback("flow", flow_id, payload.version)
    except version_repo.VersionNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "VERSION_NOT_FOUND", "message": str(exc), "detail": None},
        )
    except version_repo.VersionAlreadyCurrent as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "VERSION_ALREADY_CURRENT", "message": str(exc), "detail": None},
        )
    return await load_flow(flow_id)


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(flow_id: str):
    deleted = await db.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{flow_id}/validate")
async def validate_flow_endpoint(flow_id: str):
    flow = await load_flow(flow_id)
    if flow.dsl_version != 2:
        return _legacy_flow_response()
    return await validate_flow_runtime(flow)


@router.post("/{flow_id}/run", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def start_run(flow_id: str, payload: dict | None = None):
    flow = await load_flow(flow_id)
    if flow.dsl_version != 2:
        return _legacy_flow_response()

    result = await validate_flow_runtime(flow)
    if not result.valid:
        return _invalid_flow_response(result.errors)

    # Agent 节点需要模型；没配 Key 就不要创建 run 再让它失败
    if any(node.type == "agent" for node in flow.nodes):
        llm = await get_llm_config()
        if not llm.configured:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "LLM_NOT_CONFIGURED",
                    "message": "尚未配置 LLM API Key，请先在「模型设置」里填写后再运行",
                    "detail": None,
                },
            )

    inputs = (payload or {}).get("inputs", {}) if payload else {}
    # 运行时用「当前保存的版本」；清单记录发布指针与当前指纹，供回放 / 评测定位
    manifest = await run_manifest.build_flow_run_manifest(flow)
    mode = str(manifest.get("versionMode") or "draft")
    run = Run(
        id=f"run_{uuid.uuid4().hex[:8]}",
        target_type="flow",
        target_id=flow_id,
        target_version=flow.version,
        version_mode=mode,  # type: ignore[arg-type]
        manifest=manifest,
        status=RunStatus.PENDING,
        inputs=inputs,
        started_at=utc_now(),
    )
    await db.execute(
        "INSERT INTO runs (id, target_type, target_id, target_version, version_mode, "
        "manifest_json, status, inputs_json, state_json, token_usage, cost, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.id,
            run.target_type,
            run.target_id,
            run.target_version,
            run.version_mode,
            orjson.dumps(manifest).decode(),
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
    run_manager.launch(run.id, executor.start(run.id, flow, inputs, stop=stop))
    return run
