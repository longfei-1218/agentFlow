"""R4：LangGraph 执行器（条件分支、有界循环、interrupt 续跑、检查点）。

模型调用仍走 conftest 里的确定性桩（app.engine.loop.stream_completion），
图执行器复用 loop 的 _run_llm_node，所以补丁照样生效。
"""
import asyncio

import pytest

from app.config import settings
from app.database import db
from app.services.event_bus import event_bus
from helpers import create_flow, edge, node, wait_for_status


@pytest.fixture(autouse=True)
def graph_runner(monkeypatch):
    monkeypatch.setattr(settings, "RUNNER", "graph")


async def _run(client, flow, inputs=None):
    response = await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": inputs or {}})
    assert response.status_code == 202, response.text
    return response.json()


async def test_graph_linear_flow_streams_and_reports_engine(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是助手", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="graph 线性",
    )
    run = await _run(client, flow, {"query": "你好"})
    final = await wait_for_status(client, run["id"], {"succeeded"})

    assert final["outputs"]["text"] == "你好，这是测试回答。"
    assert final["state"]["steps"] == 1
    assert final["tokenUsage"] == 9

    history = await event_bus.history(run["id"])
    tokens = [event for event in history if event.type == "token"]
    assert "".join(event.payload["text"] for event in tokens) == "你好，这是测试回答。"
    started = [event for event in history if event.type == "run_started"][-1]
    assert started.payload["engine"] == "langgraph"
    completed = [event for event in history if event.type == "run_completed"][-1]
    assert completed.payload["engine"] == "langgraph"


@pytest.mark.parametrize(
    ("score", "branch", "expected_node"),
    [(0.95, "true", "llm_true"), (0.2, "false", "llm_false")],
)
async def test_condition_routes_only_one_branch(client, score, branch, expected_node):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="score"),
            node("condition_1", "condition", 100, expression="{{score}} > 0.8"),
            node("llm_true", "llm", 200, system="高分", max_tokens=64),
            node("llm_false", "llm", 200, system="低分", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "condition_1"),
            edge("e_2", "condition_1", "llm_true", source_handle="true"),
            edge("e_3", "condition_1", "llm_false", source_handle="false"),
            edge("e_4", "llm_true", "output_1"),
            edge("e_5", "llm_false", "output_1"),
        ],
        name=f"condition {branch}",
    )
    run = await _run(client, flow, {"score": score})
    final = await wait_for_status(client, run["id"], {"succeeded"})

    history = await event_bus.history(run["id"])
    started_nodes = {event.node_id for event in history if event.type == "node_started"}
    assert expected_node in started_nodes
    other = "llm_false" if expected_node == "llm_true" else "llm_true"
    assert other not in started_nodes, "条件分支只应执行一条"

    branch_event = [e for e in history if e.type == "node_completed" and e.node_id == "condition_1"][-1]
    assert branch_event.payload["branch"] == branch
    assert final["state"]["branch"]["condition_1"] == branch
    assert final["state"]["steps"] == 1


async def test_condition_expression_error_is_readable(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("condition_1", "condition", 100, expression="{{missing}} > 0.8"),
            node("llm_true", "llm", 200, system="真", max_tokens=64),
            node("llm_false", "llm", 200, system="假", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "condition_1"),
            edge("e_2", "condition_1", "llm_true", source_handle="true"),
            edge("e_3", "condition_1", "llm_false", source_handle="false"),
            edge("e_4", "llm_true", "output_1"),
            edge("e_5", "llm_false", "output_1"),
        ],
        name="condition 写错",
    )
    run = await _run(client, flow, {"query": "x"})
    final = await wait_for_status(client, run["id"], {"failed"})

    assert "missing" in final["error"]
    history = await event_bus.history(run["id"])
    failed = [event for event in history if event.type == "run_failed"][-1]
    assert failed.payload["code"] == "CONDITION_INVALID"


async def test_loop_runs_body_until_max_rounds_then_exits(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("loop_1", "loop", 100, max_rounds=2, exit_condition=""),
            node("llm_1", "llm", 220, system="循环体", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "loop_1"),
            edge("e_2", "loop_1", "llm_1", source_handle="body"),
            edge("e_3", "llm_1", "loop_1"),
            edge("e_4", "loop_1", "output_1", source_handle="done"),
        ],
        name="有界循环",
    )
    run = await _run(client, flow, {"query": "x"})
    final = await wait_for_status(client, run["id"], {"succeeded"})

    assert final["state"]["loop_rounds"]["loop_1"] == 2, "max_rounds=2 表示循环体执行 2 次"
    assert final["state"]["steps"] == 2, "循环体跑了两轮，模型也调了两次"

    history = await event_bus.history(run["id"])
    branches = [
        event.payload["branch"]
        for event in history
        if event.type == "node_completed" and event.node_id == "loop_1"
    ]
    # 第 1、2 次进入走 body，第 3 次进入发现已跑满，走 done
    assert branches == ["body", "body", "done"]


async def test_loop_exit_condition_can_stop_early(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="done"),
            node("loop_1", "loop", 100, max_rounds=5, exit_condition="{{done}} == true"),
            node("llm_1", "llm", 220, system="循环体", max_tokens=64),
            node("output_1", "output", 400, fields=["done"]),
        ],
        [
            edge("e_1", "input_1", "loop_1"),
            edge("e_2", "loop_1", "llm_1", source_handle="body"),
            edge("e_3", "llm_1", "loop_1"),
            edge("e_4", "loop_1", "output_1", source_handle="done"),
        ],
        name="退出条件",
    )
    run = await _run(client, flow, {"done": True})
    final = await wait_for_status(client, run["id"], {"succeeded"})

    assert final["state"]["loop_rounds"].get("loop_1", 0) == 0, "退出条件一上来就为真，一轮都不算"
    assert final["state"]["steps"] == 0, "退出条件一上来就为真，循环体不该执行"
    assert final["outputs"]["done"] is True

    history = await event_bus.history(run["id"])
    branches = [
        event.payload["branch"]
        for event in history
        if event.type == "node_completed" and event.node_id == "loop_1"
    ]
    assert branches == ["done"]


async def test_interrupt_pauses_and_resume_continues_from_checkpoint(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("human_1", "human", 200, message="允许继续？", timeout=300),
            node("output_1", "output", 400, fields=["approved"]),
        ],
        [edge("e_1", "input_1", "human_1"), edge("e_2", "human_1", "output_1")],
        name="interrupt 审批",
    )
    run = await _run(client, flow, {"query": "x"})
    paused = await wait_for_status(client, run["id"], {"waiting_human"})
    assert paused["state"]["human_pending"] == "human_1"

    history = await event_bus.history(run["id"])
    human_events = [e for e in history if e.type == "human_required"]
    assert len(human_events) == 1
    assert human_events[0].payload["engine"] == "langgraph"
    started_human = [
        e for e in history if e.type == "node_started" and e.node_id == "human_1"
    ]
    assert len(started_human) == 1

    # checkpointer 真的把图状态写进了我们的 SQLite，而不是只在内存里
    row = await db.fetchone("SELECT count(*) AS n FROM checkpoints")
    assert row["n"] >= 1

    await client.post(f"/api/runs/{run['id']}/resume", json={"approved": True})
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["approved"] is True
    assert final["state"]["human_pending"] is None

    history = await event_bus.history(run["id"])
    started_human = [
        e for e in history if e.type == "node_started" and e.node_id == "human_1"
    ]
    assert len(started_human) == 1, "续跑重入 human 节点时不该重复发 node_started"
    completed_human = [
        e for e in history if e.type == "node_completed" and e.node_id == "human_1"
    ]
    assert len(completed_human) == 1


async def test_graph_cancel_stops_the_loop(client, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_STEP_DELAY", 0.35)
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("prompt_1", "prompt", 100, template="{{query}}"),
            node("llm_1", "llm", 200, system="你是助手", max_tokens=64),
            node("prompt_2", "prompt", 300, template="{{text}}"),
            node("llm_2", "llm", 400, system="第二轮", max_tokens=64),
            node("output_1", "output", 500, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "prompt_1"),
            edge("e_2", "prompt_1", "llm_1"),
            edge("e_3", "llm_1", "prompt_2"),
            edge("e_4", "prompt_2", "llm_2"),
            edge("e_5", "llm_2", "output_1"),
        ],
        name="graph 取消",
    )
    run = await _run(client, flow, {"query": "x"})
    await asyncio.sleep(0.4)

    cancelled = (await client.post(f"/api/runs/{run['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"

    count_before = len(await event_bus.history(run["id"]))
    await asyncio.sleep(1.2)
    final = (await client.get(f"/api/runs/{run['id']}")).json()
    assert final["status"] == "cancelled"
    assert len(await event_bus.history(run["id"])) == count_before


async def test_node_types_reports_engine_and_control_nodes_implemented(client):
    payload = (await client.get("/api/node-types")).json()
    assert payload["engine"] == "graph"
    assert "graph" in payload["engines"]

    specs = {item["type"]: item for item in payload["types"]}
    assert specs["condition"]["implemented"] is True
    assert specs["loop"]["implemented"] is True
    assert specs["mcp"]["implemented"] is False
