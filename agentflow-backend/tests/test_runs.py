"""Run 生命周期（Flow v2）：SSE、筛选、节点统计、取消、审批续跑、序号恢复。"""
import asyncio

import pytest

from app.engine import agent_runner
from app.services.event_bus import event_bus
from app.services.llm import LLMDelta
from helpers import create_flow, edge, node, wait_for_status


async def _agent(client, name: str = "运行 Agent"):
    payload = {
        "name": name,
        "description": name,
        "variables": [{"key": "query", "type": "string", "required": True}],
        "prompt": {"system": "回答用户", "template": "{{query}}"},
        "resources": [],
        "model": {"name": "fake", "temperature": 0},
        "output": {"description": "", "schema": None},
    }
    response = await client.post("/api/agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _simple_flow(client, name="简单流程"):
    agent = await _agent(client, f"{name} Agent")
    return await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string", "required": True}]),
            node("a1", "agent", agentId=agent["id"], inputMap={"query": "{{start.query}}"}),
            node("end_1", "end", outputs=["a1.output.text"]),
        ],
        [edge("e_1", "start_1", "a1"), edge("e_2", "a1", "end_1")],
        name=name,
    )


@pytest.fixture(autouse=True)
def fast_agent(monkeypatch):
    async def stream(config, messages, **kwargs):
        yield LLMDelta(text="你好，", delta_tokens=3, cost=0.00001)
        yield LLMDelta(text="这是测试回答。", delta_tokens=2, cost=0.00002)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)


@pytest.mark.asyncio
async def test_run_streams_events_until_terminal(client):
    flow = await _simple_flow(client)
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "你好"}})).json()

    async def read_stream() -> str:
        body = ""
        async with client.stream("GET", f"/api/runs/{run['id']}/events") as response:
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                body += chunk
                if "run_completed" in body or "run_failed" in body:
                    break
        return body

    body = await asyncio.wait_for(read_stream(), timeout=15)
    assert "event: run_started" in body
    assert "event: node_started" in body
    assert "event: token" in body
    assert "event: run_completed" in body

    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["text"] == "你好，这是测试回答。"


@pytest.mark.asyncio
async def test_list_runs_filters_by_flow(client):
    flow_a = await _simple_flow(client, name="A")
    flow_b = await _simple_flow(client, name="B")
    run_a = (await client.post(f"/api/flows/{flow_a['id']}/run", json={"inputs": {"query": "a"}})).json()
    run_b = (await client.post(f"/api/flows/{flow_b['id']}/run", json={"inputs": {"query": "b"}})).json()
    await wait_for_status(client, run_b["id"], {"succeeded"})

    listed = (await client.get("/api/runs", params={"flow_id": flow_a["id"]})).json()
    assert {item["id"] for item in listed} == {run_a["id"]}


@pytest.mark.asyncio
async def test_run_stats_aggregates_per_node(client):
    flow = await _simple_flow(client)
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await wait_for_status(client, run["id"], {"succeeded"})

    stats = (await client.get(f"/api/runs/{run['id']}/stats")).json()
    node_ids = {item["nodeId"] for item in stats["nodes"]}
    assert node_ids == {"start_1", "a1", "end_1"}
    agent_node = next(item for item in stats["nodes"] if item["nodeId"] == "a1")
    assert agent_node["tokens"] > 0
    assert stats["totalTokens"] > 0


@pytest.mark.asyncio
async def test_cancel_stops_agent_run(client, monkeypatch):
    async def slow_stream(config, messages, **kwargs):
        await asyncio.sleep(1.5)
        yield LLMDelta(text="迟到的回答", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", slow_stream)
    flow = await _simple_flow(client, name="可取消")
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await asyncio.sleep(0.3)

    cancelled = (await client.post(f"/api/runs/{run['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"

    count_before = len(await event_bus.history(run["id"]))
    await asyncio.sleep(1.6)
    final = (await client.get(f"/api/runs/{run['id']}")).json()
    assert final["status"] == "cancelled"
    assert final["outputs"] is None
    assert len(await event_bus.history(run["id"])) == count_before


@pytest.mark.asyncio
async def test_resume_continues_after_human_approval(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("human_1", "human", message="确认执行高危操作？", timeout=300),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "human_1"), edge("e_2", "human_1", "end_1")],
        name="审批流程",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await wait_for_status(client, run["id"], {"waiting_human"})

    resumed = (await client.post(f"/api/runs/{run['id']}/resume", json={"approved": True})).json()
    assert resumed["status"] == "running"

    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["state"]["human_pending"] is None
    history = await event_bus.history(run["id"])
    assert any(event.type == "human_required" for event in history)
    assert history[-1].type == "run_completed"


@pytest.mark.asyncio
async def test_rejecting_approval_cancels_run(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("human_1", "human", message="拒绝"),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "human_1"), edge("e_2", "human_1", "end_1")],
        name="拒绝审批",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await wait_for_status(client, run["id"], {"waiting_human"})

    rejected = (await client.post(f"/api/runs/{run['id']}/resume", json={"approved": False})).json()
    assert rejected["status"] == "cancelled"


@pytest.mark.asyncio
async def test_seq_recovers_from_database_after_bus_restart(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("end_1", "end", outputs=["start.query"]),
        ],
        [edge("e_1", "start_1", "end_1")],
        name="序号恢复",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await wait_for_status(client, run["id"], {"succeeded"})

    history = await event_bus.history(run["id"])
    max_before = max(event.seq for event in history)

    event_bus._seq.pop(run["id"], None)  # 模拟服务重启：内存游标丢失
    recovered = await event_bus.emit(run["id"], "node_completed", "start_1", {"ok": True})
    assert recovered.seq == max_before + 1
