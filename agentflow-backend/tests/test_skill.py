"""R5：skill 子流程节点 —— 内联执行、输出合并、递归/审批拦截。"""
from helpers import create_flow, edge, node, wait_for_status


async def _child_flow(client) -> dict:
    return await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是子流程", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="子流程：改写",
    )


async def test_skill_node_runs_subflow_and_merges_outputs(client):
    child = await _child_flow(client)

    parent = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node(
                "skill_1",
                "skill",
                200,
                flow_id=child["id"],
                inputs_template='{"query": "{{query}}"}',
            ),
            node("output_1", "output", 400, fields=["text", "result"]),
        ],
        [edge("e_1", "input_1", "skill_1"), edge("e_2", "skill_1", "output_1")],
        name="父流程：调用子流程",
    )

    run = (
        await client.post(
            f"/api/flows/{parent['id']}/run", json={"inputs": {"query": "把这句话改写一下"}}
        )
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})

    # 子流程 llm 由测试桩固定回答；输出合并回父变量，result 里保留结构化副本
    assert final["outputs"]["text"] == "你好，这是测试回答。"
    assert "这是测试回答" in final["outputs"]["result"]

    from app.services.event_bus import event_bus
    import orjson

    history = await event_bus.history(run["id"])
    dumped = orjson.dumps(
        [{"type": event.type, "nodeId": event.node_id, "payload": event.payload} for event in history]
    ).decode()
    assert '"skillFlow"' in dumped
    assert child["id"] in dumped

    state = final["state"]
    assert state["skill_calls"][0]["flowId"] == child["id"]
    # 子流程花的 token 记在父 run 上：一次运行的总账不能漏
    assert final["tokenUsage"] > 0


async def test_skill_node_blocks_self_recursion(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("skill_1", "skill", 200, flow_id="placeholder", inputs_template="{}"),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "skill_1"), edge("e_2", "skill_1", "output_1")],
        name="自调用",
    )

    # 创建时还不知道自己的 id，拿到 id 后再把 skill 指向自己
    node_with_self = node("skill_1", "skill", 200, flow_id=flow["id"], inputs_template="{}")
    updated = await client.put(
        f"/api/flows/{flow['id']}",
        json={
            "name": flow["name"],
            "nodes": [
                node("input_1", "input", name="query"),
                node_with_self,
                node("output_1", "output", 400, fields=["text"]),
            ],
            "edges": [edge("e_1", "input_1", "skill_1"), edge("e_2", "skill_1", "output_1")],
        },
    )
    assert updated.status_code == 200, updated.text

    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "hi"}})).json()
    final = await wait_for_status(client, run["id"], {"failed"})
    assert "递归" in (final["error"] or "")

    from app.services.event_bus import event_bus
    import orjson

    history = await event_bus.history(run["id"])
    dumped = orjson.dumps(
        [{"type": event.type, "payload": event.payload} for event in history]
    ).decode()
    assert "SKILL_RECURSION" in dumped


async def test_skill_node_rejects_child_with_human_approval(client):
    child = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("human_1", "human", 200, message="批一下"),
            node("output_1", "output", 400, fields=["approved"]),
        ],
        [edge("e_1", "input_1", "human_1"), edge("e_2", "human_1", "output_1")],
        name="含审批的子流程",
    )

    parent = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("skill_1", "skill", 200, flow_id=child["id"], inputs_template="{}"),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "skill_1"), edge("e_2", "skill_1", "output_1")],
        name="调用含审批子流程",
    )

    run = (await client.post(f"/api/flows/{parent['id']}/run", json={"inputs": {"query": "x"}})).json()
    final = await wait_for_status(client, run["id"], {"failed"})
    assert "人工审批" in (final["error"] or "")
