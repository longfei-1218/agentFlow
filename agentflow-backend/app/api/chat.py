"""Agent 对话 API：会话 + 每轮一次 Agent Run。"""
import uuid

import orjson
from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.engine.agent_runner import AgentRunError
from app.engine.agent_task import create_agent_run, start_agent_run
from app.models.agent import Agent
from app.models.chat import (
    ChatTurnCreate,
    ChatTurnResult,
    Conversation,
    ConversationCreate,
    ConversationDetail,
)
from app.models.run import RunStatus
from app.services import agent_repo, agent_service
from app.services.chat_repo import (
    ConversationNotFound,
    add_turn,
    build_history,
    conversation_messages,
    create_conversation,
    delete_conversation,
    find_or_create_conversation,
    get_conversation,
    list_conversations,
    touch_conversation,
    turn_count,
)
from app.services.event_bus import event_bus
from app.services.flow_repo import load_flow
from app.services.run_manager import run_manager
from app.services.run_repo import max_seq
from app.services.settings_repo import get_llm_config

router = APIRouter(prefix="/chat", tags=["chat"])


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": "CONVERSATION_NOT_FOUND", "message": message, "detail": None},
    )


def _chat_variable(agent: Agent) -> str | None:
    if any(var.key == "query" for var in agent.variables):
        return "query"
    for var in agent.variables:
        if var.type == "string":
            return var.key
    return None


@router.post("/conversations", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create(payload: ConversationCreate):
    try:
        agent = await agent_repo.get_agent(payload.agent_id)
    except agent_repo.AgentNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "AGENT_NOT_FOUND", "message": str(exc), "detail": None},
        )
    if payload.flow_id or payload.node_id:
        if not (payload.flow_id and payload.node_id):
            return JSONResponse(
                status_code=422,
                content={
                    "code": "CHAT_SCOPE_INVALID",
                    "message": "flowId 与 nodeId 必须同时提供，或都不提供",
                    "detail": None,
                },
            )
        flow = await load_flow(payload.flow_id)
        node = next((item for item in flow.nodes if item.id == payload.node_id), None)
        node_agent_id = ""
        if node is not None:
            node_agent_id = str(
                node.config.get("agent_id") or node.config.get("agentId") or ""
            )
        if node is None or node.type != "agent" or node_agent_id != agent.id:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "CHAT_SCOPE_INVALID",
                    "message": "flowId/nodeId 没有指向该 Agent 的流程节点",
                    "detail": None,
                },
            )
    return await create_conversation(
        agent.id,
        flow_id=payload.flow_id,
        node_id=payload.node_id,
        title=payload.title or agent.name,
    )


@router.get("/conversations", response_model=list[Conversation])
async def list_all(
    agent_id: str | None = None,
    flow_id: str | None = None,
    node_id: str | None = None,
):
    return await list_conversations(agent_id, flow_id=flow_id, node_id=node_id)


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

    try:
        agent = await agent_repo.get_agent(conversation.agent_id)
    except agent_repo.AgentNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "AGENT_NOT_FOUND", "message": str(exc), "detail": None},
        )

    chat_var = _chat_variable(agent)
    variables = dict(payload.variables)
    chat_text: str | None = None
    if chat_var is not None:
        variables[chat_var] = payload.content.strip()
        if f"{{{{{chat_var}}}}}" not in agent.prompt.template:
            # 变量存在但模板没引用它，消息同样不能丢
            chat_text = payload.content.strip()
    else:
        # 零变量 / 没有 string 变量的 Agent：把消息追加到模板末尾
        chat_text = payload.content.strip()
    if any(var.key == "history" for var in agent.variables):
        variables["history"] = await build_history(conversation_id)

    try:
        variables = agent_service.normalize_variables(agent, variables)
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
                "message": "尚未配置 LLM API Key，请先在「模型设置」里填写后再对话",
                "detail": None,
            },
        )

    run = await create_agent_run(agent, variables, conversation_id=conversation_id)
    is_first = await turn_count(conversation_id) == 0
    turn_id = await add_turn(conversation_id, payload.content.strip(), run.id)
    if is_first and conversation.title in ("新对话", agent.name):
        title = payload.content.strip().splitlines()[0][:24]
        await touch_conversation(conversation_id, title=title or conversation.title)

    event_bus.seed_seq(run.id, await max_seq(run.id))
    run_manager.launch(
        run.id, start_agent_run(run.id, agent, variables, chat_text=chat_text)
    )
    return ChatTurnResult(
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id=run.id,
        status=RunStatus.PENDING.value,
    )
