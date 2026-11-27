"""Agent 对话：会话隔离、历史回灌、每轮 Agent Run。"""
import asyncio

import pytest

from app.engine import agent_runner
from app.services.llm import LLMDelta
from helpers import create_flow, edge, node, wait_for_status


async def _agent(client, name: str, template: str = "{{query}}"):
    payload = {
        "name": name,
        "description": name,
        "variables": [
            {"key": "query", "type": "string", "required": True},
            {"key": "history", "type": "string", "required": False, "default": ""},
        ],
        "prompt": {"system": f"你是 {name}", "template": template},
        "resources": [],
        "model": {"name": "fake", "temperature": 0},
        "output": {"description": "", "schema": None},
    }
    response = await client.post("/api/agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_chat_turn_creates_agent_run_and_messages(client, monkeypatch):
    async def stream(config, messages, **kwargs):
        yield LLMDelta(text=f"回复：{messages[-1]['content']}", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    agent = await _agent(client, "聊天")
    conv = (
        await client.post(
            "/api/chat/conversations",
            json={"agentId": agent["id"], "title": "测试会话"},
        )
    ).json()
    turn = (
        await client.post(
            f"/api/chat/conversations/{conv['id']}/turns",
            json={"content": "你好", "variables": {}},
        )
    ).json()
    await wait_for_status(client, turn["runId"], {"succeeded"})

    detail = (await client.get(f"/api/chat/conversations/{conv['id']}")).json()
    assert detail["agentId"] == agent["id"]
    assert detail["flowId"] is None and detail["nodeId"] is None
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"].startswith("回复：你好")


@pytest.mark.asyncio
async def test_chat_history_is_scoped_and_replayed(client, monkeypatch):
    seen: list[str] = []

    async def stream(config, messages, **kwargs):
        seen.append(messages[-1]["content"])
        yield LLMDelta(text=f"第{len(seen)}轮回答", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    agent = await _agent(client, "历史", "历史：{{history}}\\n问题：{{query}}")
    conv = (
        await client.post(
            "/api/chat/conversations", json={"agentId": agent["id"]}
        )
    ).json()
    first = (
        await client.post(
            f"/api/chat/conversations/{conv['id']}/turns",
            json={"content": "第一问"},
        )
    ).json()
    await wait_for_status(client, first["runId"], {"succeeded"})
    second = (
        await client.post(
            f"/api/chat/conversations/{conv['id']}/turns",
            json={"content": "第二问"},
        )
    ).json()
    await wait_for_status(client, second["runId"], {"succeeded"})
    assert "用户：第一问" in seen[-1]
    assert "助手：第1轮回答" in seen[-1]

    other_agent = await _agent(client, "别的")
    other = (
        await client.post(
            "/api/chat/conversations", json={"agentId": other_agent["id"]}
        )
    ).json()
    mine = (
        await client.get(
            "/api/chat/conversations", params={"agent_id": agent["id"]}
        )
    ).json()
    assert {item["id"] for item in mine} == {conv["id"]}
    assert other["id"] not in {item["id"] for item in mine}


@pytest.mark.asyncio
async def test_flow_scoped_conversation_requires_agent_node(client):
    agent = await _agent(client, "节点")
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[]),
            node("a1", "agent", agentId=agent["id"], inputMap={}),
            node("end_1", "end", outputs=[]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )
    ok = await client.post(
        "/api/chat/conversations",
        json={"agentId": agent["id"], "flowId": flow["id"], "nodeId": "a1"},
    )
    assert ok.status_code == 201, ok.text
    bad = await client.post(
        "/api/chat/conversations",
        json={"agentId": agent["id"], "flowId": flow["id"], "nodeId": "end_1"},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "CHAT_SCOPE_INVALID"
