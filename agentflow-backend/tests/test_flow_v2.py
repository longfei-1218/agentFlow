"""Flow v2：start/agent/condition/loop/human/end。"""
import asyncio
import json

import pytest

from app.engine import agent_runner
from app.models.flow import Flow
from app.services.flow_service import validate_flow
from helpers import create_flow, edge, node, wait_for_status


def _fake_stream(messages_seen: list[str]):
    async def stream(config, messages, **kwargs):
        user = messages[-1]["content"]
        messages_seen.append(user)
        await asyncio.sleep(0)
        if "你是 A1" in messages[0]["content"]:
            yield __import__("app.services.llm", fromlist=["LLMDelta"]).LLMDelta(
                text="退款", delta_tokens=2, cost=0.00001
            )
        else:
            yield __import__("app.services.llm", fromlist=["LLMDelta"]).LLMDelta(
                text=f"收到意图：{user}", delta_tokens=2, cost=0.00001
            )

    return stream


async def _agent(
    client, name: str, system: str, variables: list[dict], model: str = "fake", template: str = "{{query}}"
):
    payload = {
        "name": name,
        "description": name,
        "variables": variables,
        "prompt": {"system": system, "template": template},
        "resources": [],
        "model": {"name": model, "temperature": 0, "maxTokens": 128},
        "output": {"description": "", "schema": None},
    }
    response = await client.post("/api/agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_two_agents_chain_via_input_map(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(agent_runner.llm, "stream_completion", _fake_stream(seen))
    a1 = await _agent(client, "分类", "你是 A1，只输出意图词。", [{"key": "query", "type": "string", "required": True}])
    a2 = await _agent(
        client,
        "回复",
        "你是 A2，根据意图回复。",
        [
            {"key": "query", "type": "string", "required": True},
            {"key": "intent", "type": "string", "required": True},
        ],
        template="{{intent}}",
    )
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("a1", "agent", agentId=a1["id"], inputMap={"query": "{{start.query}}"}),
            node(
                "a2",
                "agent",
                agentId=a2["id"],
                inputMap={
                    "query": "{{start.query}}",
                    "intent": "{{a1.output.text}}",
                },
            ),
            node("end_1", "end", outputs=["a2.output.text"]),
        ],
        [
            edge("e1", "start_1", "a1"),
            edge("e2", "a1", "a2"),
            edge("e3", "a2", "end_1"),
        ],
    )
    run = (
        await client.post(
            f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "我要退款"}}
        )
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["text"].startswith("收到意图：退款")
    assert seen[-1] == "退款"
    assert final["state"]["nodes"]["a1"]["output"]["text"] == "退款"
    assert final["state"]["nodes"]["a2"]["agentId"] == a2["id"]


@pytest.mark.asyncio
async def test_condition_routes_true_branch(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(agent_runner.llm, "stream_completion", _fake_stream(seen))
    agent = await _agent(client, "判断", "你是 A1，只输出 yes。", [{"key": "query", "type": "string"}])
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("cond", "condition", expression='{{a1.output.text}} == "退款"'),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [
            edge("e1", "start_1", "a1"),
            edge("e2", "a1", "cond"),
            edge("e3", "cond", "end_1", "true"),
            edge("e4", "cond", "end_1", "false"),
        ],
    )
    run = (
        await client.post(
            f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "退款"}}
        )
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["state"]["branch"]["cond"] == "true"


@pytest.mark.asyncio
async def test_loop_runs_body_then_done(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(agent_runner.llm, "stream_completion", _fake_stream(seen))
    agent = await _agent(client, "循环", "你是 A2，记录轮次。", [{"key": "query", "type": "string"}])
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("loop_1", "loop", maxRounds=2),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [
            edge("e1", "start_1", "loop_1"),
            edge("e2", "loop_1", "a1", "body"),
            edge("e3", "a1", "loop_1"),
            edge("e4", "loop_1", "end_1", "done"),
        ],
    )
    run = (
        await client.post(
            f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "轮次"}}
        )
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"}, timeout=20)
    assert final["state"]["loop_rounds"]["loop_1"] == 2


@pytest.mark.asyncio
async def test_human_pauses_and_resumes(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("human_1", "human", message="同意吗？"),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [
            edge("e1", "start_1", "human_1"),
            edge("e2", "human_1", "end_1"),
        ],
    )
    run = (
        await client.post(
            f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "审批"}}
        )
    ).json()
    paused = await wait_for_status(client, run["id"], {"waiting_human"})
    assert paused["status"] == "waiting_human"
    resumed = await client.post(f"/api/runs/{run['id']}/resume", json={"approved": True})
    assert resumed.status_code == 200
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["query"] == "审批"


@pytest.mark.asyncio
async def test_zero_variable_agent_runs_in_flow(client, monkeypatch):
    """零变量 Agent 不依赖 inputMap，按固定模板在流程节点里运行。"""
    seen: list[str] = []
    monkeypatch.setattr(agent_runner.llm, "stream_completion", _fake_stream(seen))
    agent = await _agent(
        client,
        "固定",
        "你是固定角色。",
        [],
        template="请保持角色设定。",
    )
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[]),
            node("a1", "agent", agentId=agent["id"], inputMap={}),
            node("end_1", "end", outputs=[]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )
    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["text"] == "收到意图：请保持角色设定。"
    assert seen[-1] == "请保持角色设定。"


def test_legacy_flow_is_rejected():
    result = validate_flow(
        Flow(
            id="flow_old",
            name="旧",
            dsl_version=1,
            nodes=[],
            edges=[],
        )
    )
    assert result.valid is False
    assert "旧 DSL" in result.errors[0].message


@pytest.mark.asyncio
async def test_required_agent_variable_missing_is_rejected(client):
    agent = await _agent(client, "必选", "你是 A1。", [{"key": "query", "type": "string"}])
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[]),
            node("a1", "agent", agentId=agent["id"], inputMap={}),
            node("end_1", "end", outputs=[]),
        ],
        [edge("e1", "start_1", "a1"), edge("e2", "a1", "end_1")],
    )
    response = await client.post(f"/api/flows/{flow['id']}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("必选变量 query" in item["message"] for item in body["errors"])
