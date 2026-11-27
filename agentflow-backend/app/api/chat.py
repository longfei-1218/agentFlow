"""对话模式 API（R5.1）：会话 CRUD + 每轮触发一次流程 run。

这一层只做「会话 → 一次普通 run」的转译：执行、SSE、取消、回放全部复用
现有 run 体系，不新增执行器。
"""
import uuid

import orjson
from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.database import db
from app.engine import executor
from app.models.chat import (
    ChatTurnCreate,
    ChatTurnResult,
    Conversation,
    ConversationCreate,
    ConversationDetail,
)
from app.models.run import Run, RunStatus
from app.services.chat_repo import (
    ConversationNotFound,
    add_turn,
    build_history,
    conversation_messages,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    touch_conversation,
    turn_count,
)
from app.services.event_bus import event_bus, utc_now
from app.services.flow_repo import load_flow
from app.services.flow_service import validate_flow
from app.services.run_manager import run_manager
from app.services.run_repo import max_seq
from app.services.settings_repo import get_llm_config

router = APIRouter(prefix="/chat", tags=["chat"])


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": "CONVERSATION_NOT_FOUND", "message": message, "detail": None},
    )


@router.post("/conversations", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create(payload: ConversationCreate):
    flow = await load_flow(payload.flow_id)
    return await create_conversation(flow.id, payload.title or flow.name)


@router.get("/conversations", response_model=list[Conversation])
async def list_all(flow_id: str | None = None):
    return await list_conversations(flow_id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def detail(conversation_id: str):
    try:
        conversation = await get_conversation(conversation_id)
    except ConversationNotFound as exc:
        return _not_found(str(exc))
    return ConversationDetail(
        **conversation.model_dump(), messages=await conversation_messages(conversation_id)
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(conversation_id: str):
    try:
        await delete_conversation(conversation_id)
    except ConversationNotFound as exc:
        return _not_found(str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=ChatTurnResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_turn(conversation_id: str, payload: ChatTurnCreate):
    try:
        conversation = await get_conversation(conversation_id)
    except ConversationNotFound as exc:
        return _not_found(str(exc))

    flow = await load_flow(conversation.flow_id)
    validation = validate_flow(flow)
    if not validation.valid:
        return JSONResponse(
            status_code=422,
            content={
                "code": "FLOW_INVALID",
                "message": "流程校验未通过，无法在对话里执行",
                "detail": [issue.model_dump(by_alias=True) for issue in validation.errors],
            },
        )

    # 对话模式暂不做审批：父 run 暂停后聊天页没有对应的批准入口，先明确拒绝
    if any(node.type == "human" for node in flow.nodes):
        return JSONResponse(
            status_code=409,
            content={
                "code": "CHAT_HUMAN_UNSUPPORTED",
                "message": "对话模式暂不支持含人工审批（human）节点的流程，请先在该流程里去掉审批，或改用编辑器运行",
                "detail": None,
            },
        )

    if any(node.type == "llm" for node in flow.nodes):
        llm = await get_llm_config()
        if not llm.configured:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "LLM_NOT_CONFIGURED",
                    "message": "尚未配置 LLM API Key，请先在「模型设置」里填写后再对话",
                    "detail": None,
                },
            )

    content = payload.content.strip()
    history = await build_history(conversation_id)
    inputs = {"query": content, "history": history}

    run = Run(
        id=f"run_{uuid.uuid4().hex[:8]}",
        flow_id=flow.id,
        flow_version=flow.version,
        status=RunStatus.PENDING,
        inputs=inputs,
        started_at=utc_now(),
        conversation_id=conversation_id,
    )
    await db.execute(
        "INSERT INTO runs (id, flow_id, flow_version, status, inputs_json, state_json, "
        "token_usage, cost, started_at, conversation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.id,
            flow.id,
            flow.version,
            run.status.value,
            orjson.dumps(inputs).decode(),
            "{}",
            0,
            0.0,
            run.started_at,
            conversation_id,
        ),
    )

    is_first = await turn_count(conversation_id) == 0
    turn_id = await add_turn(conversation_id, content, run.id)
    if is_first and conversation.title in ("新对话", flow.name):
        title = content.splitlines()[0][:24].strip()
        await touch_conversation(conversation_id, title=title or conversation.title)

    event_bus.seed_seq(run.id, await max_seq(run.id))
    stop = run_manager.cancel_token(run.id)
    run_manager.launch(run.id, executor.start(run.id, flow, inputs, stop=stop))
    return ChatTurnResult(
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id=run.id,
        status=run.status.value,
    )
