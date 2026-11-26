"""Run 生命周期：SSE 事件流、筛选、节点统计、取消、审批续跑、序号恢复。"""
import asyncio

from app.services.event_bus import event_bus
from helpers import create_flow, edge, node, wait_for_status


async def _simple_flow(client, name="简单流程"):
    """input -> llm -> output，演示执行器会推 token 流。"""
    return await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, model="gpt-4o-mini", system="你是助手", max_tokens=128),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name=name,
    )


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
    assert final["outputs"]["text"], "output 节点按 fields 取字段，text 必须有值"


async def test_list_runs_filters_by_flow(client):
    flow_a = await _simple_flow(client, name="A")
    flow_b = await _simple_flow(client, name="B")
    run_a = (await client.post(f"/api/flows/{flow_a['id']}/run", json={"inputs": {}})).json()
    run_b = (await client.post(f"/api/flows/{flow_b['id']}/run", json={"inputs": {}})).json()
    await wait_for_status(client, run_b["id"], {"succeeded"})

    listed = (await client.get("/api/runs", params={"flow_id": flow_a["id"]})).json()
    assert {item["id"] for item in listed} == {run_a["id"]}


async def test_run_stats_aggregates_per_node(client):
    flow = await _simple_flow(client)
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})).json()
    await wait_for_status(client, run["id"], {"succeeded"})

    stats = (await client.get(f"/api/runs/{run['id']}/stats")).json()
    node_ids = {item["nodeId"] for item in stats["nodes"]}
    assert node_ids == {"input_1", "llm_1", "output_1"}
    assert stats["nodes"][1]["tokens"] > 0 or any(n["tokens"] for n in stats["nodes"])
    assert stats["totalTokens"] > 0


async def test_cancel_stops_background_runner(client, slow_demo):
    flow = await _simple_flow(client, name="可取消")
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})).json()
    await asyncio.sleep(0.4)  # 让它推进到 llm 节点中途

    cancelled = (await client.post(f"/api/runs/{run['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"

    count_before = len(await event_bus.history(run["id"]))
    await asyncio.sleep(1.2)  # 足够执行器跑完剩余节点的时长

    final = (await client.get(f"/api/runs/{run['id']}")).json()
    assert final["status"] == "cancelled", "取消后不能被后台任务改写回 succeeded"
    assert final["outputs"] is None
    assert len(await event_bus.history(run["id"])) == count_before, "取消后不应再产生事件"


async def test_resume_continues_after_human_approval(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("human_1", "human", 200, message="确认执行高危操作？", timeout=300),
            node("output_1", "output", 400, fields=["approved"]),
        ],
        [edge("e_1", "input_1", "human_1"), edge("e_2", "human_1", "output_1")],
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


async def test_rejecting_approval_cancels_run(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("human_1", "human", 200, message="拒绝"),
            node("output_1", "output", 400, fields=["approved"]),
        ],
        [edge("e_1", "input_1", "human_1"), edge("e_2", "human_1", "output_1")],
        name="拒绝审批",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})).json()
    await wait_for_status(client, run["id"], {"waiting_human"})

    rejected = (await client.post(f"/api/runs/{run['id']}/resume", json={"approved": False})).json()
    assert rejected["status"] == "cancelled"


async def test_seq_recovers_from_database_after_bus_restart(client):
    flow = await _simple_flow(client, name="序号恢复")
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})).json()
    await wait_for_status(client, run["id"], {"succeeded"})

    history = await event_bus.history(run["id"])
    max_before = max(event.seq for event in history)

    event_bus._seq.pop(run["id"], None)  # 模拟服务重启：内存游标丢失
    recovered = await event_bus.emit(run["id"], "node_completed", "llm_1", {"ok": True})
    assert recovered.seq == max_before + 1
