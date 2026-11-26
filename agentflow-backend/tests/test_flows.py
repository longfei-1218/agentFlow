"""Flow CRUD / 版本语义 / 校验规则。"""
from helpers import create_flow, edge, node


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_create_generates_default_flow_when_structure_omitted(client):
    response = await client.post("/api/flows", json={"name": "演示"})
    assert response.status_code == 201
    flow = response.json()
    assert [n["type"] for n in flow["nodes"]] == ["input", "llm", "output"]
    assert flow["version"] == 1


async def test_explicit_empty_nodes_is_respected(client):
    flow = await create_flow(client, [], [], name="空白画布")
    assert flow["nodes"] == []
    assert flow["edges"] == []


async def test_put_keeps_version_and_publish_bumps_it(client):
    flow = await create_flow(
        client,
        [node("input_1", "input", name="query"), node("output_1", "output", 200, fields=["text"])],
        [edge("e_1", "input_1", "output_1")],
    )

    for _ in range(3):
        response = await client.put(
            f"/api/flows/{flow['id']}", json={"name": "改名", "nodes": flow["nodes"], "edges": flow["edges"]}
        )
        assert response.status_code == 200
        assert response.json()["version"] == 1, "自动保存（PUT）不应递增 version"

    published = await client.post(f"/api/flows/{flow['id']}/publish")
    assert published.status_code == 200
    assert published.json()["version"] == 2


async def test_publish_rejects_invalid_flow(client):
    flow = await create_flow(client, [], [], name="空白")
    response = await client.post(f"/api/flows/{flow['id']}/publish")
    assert response.status_code == 422
    assert response.json()["code"] == "FLOW_INVALID"


async def test_validate_detects_cycle(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("p_a", "prompt", 100, template="{{query}}"),
            node("p_b", "prompt", 200, template="{{query}}"),
            node("output_1", "output", 300, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "p_a"),
            edge("e_2", "p_a", "p_b"),
            edge("e_3", "p_b", "p_a"),
            edge("e_4", "p_b", "output_1"),
        ],
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is False
    assert any("环" in issue["message"] for issue in result["errors"])


async def test_validate_requires_entry_exit_and_condition_branches(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("cond_1", "condition", 100, expression="{{score}} > 0.8"),
            node("output_1", "output", 300, fields=["text"]),
        ],
        [edge("e_1", "input_1", "cond_1"), edge("e_2", "cond_1", "output_1", "true")],
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is False
    messages = " ".join(issue["message"] for issue in result["errors"])
    assert "true/false" in messages


async def test_run_is_blocked_by_validation(client):
    flow = await create_flow(client, [], [], name="空白")
    response = await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})
    assert response.status_code == 422
    assert response.json()["code"] == "FLOW_INVALID"
