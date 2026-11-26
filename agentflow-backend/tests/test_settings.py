"""R2-2：LLM 系统设置（存库、脱敏返回、优先级）。"""
from app.services.settings_repo import get_llm_config


async def test_default_view_falls_back_to_env(client):
    view = (await client.get("/api/settings/llm")).json()
    assert view["source"] == "env"  # 测试桩设置了 LLM_API_KEY
    assert view["hasApiKey"] is True
    assert view["apiKeyPreview"] == "sk-t…cdef"
    assert view["baseUrl"].startswith("http")


async def test_put_masks_api_key_and_never_returns_it(client):
    saved = (
        await client.put(
            "/api/settings/llm",
            json={
                "baseUrl": "http://127.0.0.1:9/v1",
                "apiKey": "sk-abcdef123456",
                "model": "test-model",
                "temperature": 0.3,
            },
        )
    ).json()

    assert saved["source"] == "db"
    assert saved["hasApiKey"] is True
    assert saved["model"] == "test-model"
    assert saved["apiKeyPreview"] == "sk-a…3456"
    assert "apiKey" not in saved, "密钥不能以任何明文形式回给前端"


async def test_put_without_api_key_keeps_existing_key(client):
    await client.put("/api/settings/llm", json={"apiKey": "sk-first-key-1234"})
    second = (await client.put("/api/settings/llm", json={"model": "changed-model"})).json()
    assert second["hasApiKey"] is True
    assert second["model"] == "changed-model"

    cleared = (await client.put("/api/settings/llm", json={"apiKey": ""})).json()
    assert cleared["hasApiKey"] is False
    assert cleared["configured"] is False


async def test_db_config_overrides_env(client):
    await client.put(
        "/api/settings/llm",
        json={"baseUrl": "http://db-wins/v1", "apiKey": "sk-db-key-9999", "model": "db-model"},
    )
    config = await get_llm_config()
    assert config.base_url == "http://db-wins/v1"
    assert config.model == "db-model"
    assert config.source == "db"


async def test_test_endpoint_reports_failure_without_touching_network(client, monkeypatch):
    """连不通时要给出可读原因，而不是抛 500。"""
    await client.put(
        "/api/settings/llm",
        json={"baseUrl": "http://127.0.0.1:1/v1", "apiKey": "sk-x", "model": "m"},
    )
    result = (await client.post("/api/settings/llm/test")).json()
    assert result["ok"] is False
    assert result["code"] in {"LLM_CONNECT_ERROR", "LLM_HTTP_ERROR"}
    assert result["latencyMs"] >= 0


async def test_models_endpoint_flags_unsupported_current_model(client, monkeypatch):
    """节点里「模型」下拉的数据源：网关列表 + 当前默认模型在不在其中。"""
    from app.services.llm import LLMError

    async def fake_models(config):
        return ["deepseek-flash", "deepseek-v4-pro"]

    monkeypatch.setattr("app.api.settings.list_models", fake_models)
    body = (await client.get("/api/settings/llm/models")).json()
    assert body["ok"] is True
    assert body["models"] == ["deepseek-flash", "deepseek-v4-pro"]
    assert body["supported"] is False  # 测试环境的默认模型不在这份列表里

    async def broken(config):
        raise LLMError("/models 返回 401", code="LLM_HTTP_ERROR")

    monkeypatch.setattr("app.api.settings.list_models", broken)
    body = (await client.get("/api/settings/llm/models")).json()
    assert body["ok"] is False
    assert body["models"] == []  # 网关卡住时前端退回手填，不让下拉变空壳
    assert "401" in body["message"]
