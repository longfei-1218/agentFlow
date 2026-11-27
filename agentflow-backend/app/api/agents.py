"""Agent v2 API：全局 Agent 库 CRUD、校验、单 Agent 运行。"""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from app.engine.agent_runner import AgentRunError, run_agent
from app.engine.agent_task import create_agent_run, start_agent_run
from app.models.agent import (
    Agent,
    AgentCreate,
    AgentRunRequest,
    AgentRunResult,
    AgentValidationResult,
)
from app.models.run import Run
from app.models.version import (
    PublishRequest,
    PublishState,
    RollbackRequest,
    VersionDetail,
)
from app.services import agent_repo, agent_service, version_repo
from app.services.event_bus import event_bus
from app.services.run_manager import run_manager
from app.services.run_repo import max_seq
from app.services.settings_repo import get_llm_config

router = APIRouter(prefix="/agents", tags=["agents"])


def _invalid(result: AgentValidationResult) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "AGENT_INVALID",
            "message": "Agent 定义不合法",
            "detail": result.model_dump(by_alias=True),
        },
    )


@router.get("", response_model=list[Agent])
async def list_agents():
    return await agent_repo.list_agents()


@router.post("", response_model=Agent, status_code=201)
async def create_agent(payload: AgentCreate):
    result = await agent_service.validate_agent(payload)
    if not result.valid:
        return _invalid(result)
    return await agent_repo.create_agent(payload)


@router.post("/validate", response_model=AgentValidationResult)
async def validate_definition(payload: AgentCreate):
    return await agent_service.validate_agent(payload)


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    try:
        return await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, payload: AgentCreate):
    try:
        await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = await agent_service.validate_agent(payload)
    if not result.valid:
        return _invalid(result)
    return await agent_repo.update_agent(agent_id, payload)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    try:
        await agent_repo.delete_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/{agent_id}/validate", response_model=AgentValidationResult)
async def validate_saved(agent_id: str):
    try:
        agent = await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = AgentCreate(**agent.model_dump(by_alias=True))
    result = await agent_service.validate_agent(payload)
    runtime_issues = await agent_service.validate_runtime_resources(payload)
    if runtime_issues:
        result.valid = False
        result.errors.extend(runtime_issues)
    return result


# ---------- R6.0 版本：发布 / 版本列表 / 回滚 ----------


def _version_error(code: str, message: str, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=422 if code != "VERSION_NOT_FOUND" else 404,
        content={"code": code, "message": message, "detail": detail},
    )


@router.post("/{agent_id}/publish", response_model=Agent)
async def publish_agent(agent_id: str, payload: PublishRequest | None = None):
    """发布 = 生成不可变快照 + 记录配置指纹 / 资源指纹 / 代码 commit。

    不检查内容是否有改动：同配置再次发布也会生成新版本，版本名用于区分场景。
    """
    try:
        agent = await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    name = (payload.name if payload else "").strip()
    if not name:
        return _version_error("VERSION_NAME_REQUIRED", "发布前请填写版本名")

    definition = AgentCreate(**agent.model_dump(by_alias=True))
    result = await agent_service.validate_agent(definition)
    if not result.valid:
        return _invalid(result)

    await version_repo.publish_agent(
        agent, name=name, note=((payload.note if payload else "") or "").strip()
    )
    return await agent_repo.get_agent(agent_id)


@router.get("/{agent_id}/versions", response_model=list[VersionDetail])
async def list_agent_versions(agent_id: str):
    try:
        await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await version_repo.list_versions("agent", agent_id)


@router.get("/{agent_id}/versions/{version}", response_model=VersionDetail)
async def get_agent_version(agent_id: str, version: int):
    try:
        return await version_repo.get_version("agent", agent_id, version)
    except version_repo.VersionNotFound as exc:
        return _version_error("VERSION_NOT_FOUND", str(exc))


@router.get("/{agent_id}/publish-state", response_model=PublishState)
async def get_agent_publish_state(agent_id: str):
    try:
        return await version_repo.publish_state("agent", agent_id)
    except version_repo.VersionNotFound as exc:
        return _version_error("VERSION_NOT_FOUND", str(exc))


@router.post("/{agent_id}/rollback", response_model=Agent)
async def rollback_agent(agent_id: str, payload: RollbackRequest):
    """把发布指针指回历史版本，并把该版本快照写回草稿；不改任何版本号。"""
    try:
        await version_repo.rollback("agent", agent_id, payload.version)
    except version_repo.VersionNotFound as exc:
        return _version_error("VERSION_NOT_FOUND", str(exc))
    except version_repo.VersionAlreadyCurrent as exc:
        return _version_error("VERSION_ALREADY_CURRENT", str(exc))
    return await agent_repo.get_agent(agent_id)


@router.post("/{agent_id}/runs", response_model=Run, status_code=202)
async def start_agent_run_api(agent_id: str, payload: AgentRunRequest):
    """异步 Agent Run（落 runs / SSE），对话与前端运行面板走这条。"""
    try:
        agent = await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        variables = agent_service.normalize_variables(agent, payload.variables)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "AGENT_INPUT_MISSING", "message": str(exc), "detail": None},
        )

    llm = await get_llm_config()
    if not llm.configured:
        return JSONResponse(
            status_code=409,
            content={
                "code": "LLM_NOT_CONFIGURED",
                "message": "尚未配置 LLM API Key",
                "detail": None,
            },
        )

    run = await create_agent_run(agent, variables)
    event_bus.seed_seq(run.id, await max_seq(run.id))
    run_manager.launch(run.id, start_agent_run(run.id, agent, variables))
    return run


@router.post("/{agent_id}/run", response_model=AgentRunResult)
async def run_saved_agent(agent_id: str, payload: AgentRunRequest):
    try:
        agent = await agent_repo.get_agent(agent_id)
    except agent_repo.AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return await run_agent(agent, payload.variables)
    except AgentRunError as exc:
        if exc.code == "LLM_NOT_CONFIGURED":
            status = 409
        elif exc.code.startswith("LLM_"):
            status = 502
        else:
            status = 422
        return JSONResponse(
            status_code=status,
            content={"code": exc.code, "message": str(exc), "detail": None},
        )
