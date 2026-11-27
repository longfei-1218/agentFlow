"""Agent v2 API：CRUD 与定义校验。"""
import pytest

BASE = {
    "name": "测试 Agent",
    "description": "只做一件事",
    "variables": [
        {"key": "query", "label": "问题", "type": "string", "required": True}
    ],
    "prompt": {"system": "你是测试助手。", "template": "回答：{{query}}"},
    "resources": [],
    "model": {"name": "", "temperature": 0.2, "maxTokens": 512, "maxToolRounds": 2},
    "output": {"description": "纯文本", "schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
}


@pytest.mark.asyncio
async def test_agent_crud_roundtrip(client):
    created = await client.post("/api/agents", json=BASE)
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["prompt"]["template"] == "回答：{{query}}"
    assert agent["output"]["schema"]["required"] == ["text"]

    listed = await client.get("/api/agents")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [agent["id"]]

    got = await client.get(f"/api/agents/{agent['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "测试 Agent"

    updated_payload = {**BASE, "name": "改名后的 Agent"}
    updated = await client.put(f"/api/agents/{agent['id']}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名后的 Agent"

    deleted = await client.delete(f"/api/agents/{agent['id']}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/agents/{agent['id']}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_agent_validate_rejects_bad_definition(client):
    bad = {
        **BASE,
        "variables": [
            {"key": "query", "type": "string", "required": True},
            {"key": "query", "type": "number", "required": False},
        ],
    }
    response = await client.post("/api/agents/validate", json=bad)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    messages = " ".join(item["message"] for item in body["errors"])
    assert "变量 key 重复" in messages


@pytest.mark.asyncio
async def test_agent_validate_rejects_unknown_prompt_variable_and_token(client):
    bad = {
        **BASE,
        "prompt": {"system": "", "template": "{{missing}} @kb[nope]"},
        "variables": [{"key": "query", "type": "string"}],
    }
    response = await client.post("/api/agents/validate", json=bad)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    messages = " ".join(item["message"] for item in body["errors"])
    assert "未定义变量" in messages
    assert "@kb[nope]" in messages


@pytest.mark.asyncio
async def test_agent_validate_reports_malformed_mcp_token(client):
    bad = {**BASE, "prompt": {"system": "", "template": "@mcp[demo]"}}
    response = await client.post("/api/agents/validate", json=bad)
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("必须写成" in item["message"] for item in body["errors"])


@pytest.mark.asyncio
async def test_agent_create_returns_422_for_invalid(client):
    bad = {**BASE, "name": ""}
    response = await client.post("/api/agents", json=bad)
    assert response.status_code == 422
    assert response.json()["code"] in {"AGENT_INVALID", "VALIDATION_ERROR"}


@pytest.mark.asyncio
async def test_agent_schema_is_camel_case_on_wire(client):
    created = await client.post("/api/agents", json=BASE)
    assert created.status_code == 201
    body = created.json()
    assert "maxTokens" in body["model"]
    assert body["output"]["schema"]["type"] == "object"
