"""R2-1（v2）：6 类节点 Schema 与配置校验。"""
from helpers import create_flow, edge, node


async def test_node_types_exposes_six_v2_schemas(client):
    response = await client.get("/api/node-types")
    assert response.status_code == 200
    data = response.json()

    assert data["categories"] == ["基础", "Agent", "控制"]
    types = {item["type"]: item for item in data["types"]}
    assert set(types) == {"start", "agent", "condition", "loop", "human", "end"}

    assert types["agent"]["configSchema"]["properties"]["agentId"]["title"] == "Agent"
    assert types["agent"]["defaultConfig"]["inputMap"] == {}
    assert types["start"]["defaultConfig"]["variables"][0]["key"] == "query"
    assert types["end"]["defaultConfig"]["outputs"] == []
    for node_type in types:
        assert types[node_type]["implemented"] is True, node_type

    assert data["engine"] in {"graph", "loop"}
    assert set(data["engines"]) == {"graph", "loop"}
    assert data["llmConfigured"] is True


async def test_node_type_detail_and_unknown_type(client):
    response = await client.get("/api/node-types/human")
    assert response.status_code == 200
    assert response.json()["defaultConfig"]["timeout"] == 300

    missing = await client.get("/api/node-types/not_a_type")
    assert missing.status_code == 404


async def test_flow_validation_reports_bad_node_config(client):
    flow = await create_flow(
        client,
        [
            node("start_1", "start", variables=[{"key": "query", "type": "string"}]),
            node("cond_1", "condition", expression=""),
            node("end_1", "end", outputs=[]),
        ],
        [edge("e_1", "start_1", "cond_1"), edge("e_2", "cond_1", "end_1", "true")],
        name="配置非法",
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()

    assert result["valid"] is False
    issues = result["errors"]
    assert any(issue["nodeId"] == "cond_1" and "expression" in issue["message"] for issue in issues)


async def test_valid_default_flow_passes_config_validation(client):
    flow = (await client.post("/api/flows", json={"name": "默认流程"})).json()
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is True, result["errors"]
