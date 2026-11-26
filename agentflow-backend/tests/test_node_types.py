"""R2-1：节点 Schema 注册表与配置校验。"""
from helpers import create_flow, edge, node


async def test_node_types_exposes_all_node_schemas(client):
    response = await client.get("/api/node-types")
    assert response.status_code == 200
    data = response.json()

    assert data["categories"] == ["基础", "模型", "工具", "控制"]
    types = {item["type"]: item for item in data["types"]}
    assert len(types) == 11, "节点库必须与前端 palette 的 11 类节点一致"

    llm = types["llm"]
    assert llm["configSchema"]["properties"]["system"]["title"] == "System Prompt"
    assert llm["configSchema"]["properties"]["max_tokens"]["minimum"] == 1
    assert llm["defaultConfig"]["model"] == ""
    assert llm["implemented"] is True

    # 尚未执行的节点要自报状态，别让界面假装能用（R4 起 condition/loop 已由 LangGraph 接管）
    assert types["mcp"]["implemented"] is False
    assert types["skill"]["implemented"] is False
    assert types["knowledge"]["implemented"] is False
    assert types["condition"]["implemented"] is True
    assert types["loop"]["implemented"] is True

    assert data["engine"] in {"graph", "loop"}  # 测试夹具把引擎锁成 loop，默认是 graph
    assert {"graph", "loop", "demo"} <= set(data["engines"])
    assert data["llmConfigured"] is True  # 测试桩给了一个假 key


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
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="", max_tokens=0),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="配置非法",
    )
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()

    assert result["valid"] is False
    issues = result["errors"]
    assert any(issue["nodeId"] == "llm_1" and "system" in issue["message"] for issue in issues)
    assert any(issue["nodeId"] == "llm_1" and "max_tokens" in issue["message"] for issue in issues)


async def test_valid_default_flow_passes_config_validation(client):
    flow = (await client.post("/api/flows", json={"name": "默认流程"})).json()
    result = (await client.post(f"/api/flows/{flow['id']}/validate")).json()
    assert result["valid"] is True, result["errors"]
