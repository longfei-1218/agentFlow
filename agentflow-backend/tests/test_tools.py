"""R3：工具注册表 CRUD + 执行器（参数校验/超时重试/幂等）+ 真 Function Calling 回路。"""
import httpx
import pytest

from app.services import tool_runner
from app.services.event_bus import event_bus
from app.services.llm import LLMDelta
from helpers import create_flow, edge, node, wait_for_status


def builtin_payload(name: str, builtin: str = "echo", **extra):
    return {
        "name": name,
        "kind": "builtin",
        "builtin": builtin,
        "description": "测试用内置工具",
        **extra,
    }


def http_payload(name: str, **extra):
    return {
        "name": name,
        "kind": "http",
        "method": "GET",
        "url": "https://example.invalid/probe",
        "paramsSchema": {"type": "object", "properties": {}},
        "backoffMs": 1,
        **extra,
    }


async def test_tool_crud_name_conflict_and_builtin_schema(client):
    response = await client.post("/api/tools", json=builtin_payload("echo_tool"))
    assert response.status_code == 201
    tool = response.json()
    # 内置工具的参数 Schema 由后端注册表给，不采信请求体里的版本
    assert tool["paramsSchema"]["required"] == ["text"]
    assert tool["kind"] == "builtin"
    assert tool["method"] == "POST" and tool["url"] == ""

    clash = await client.post("/api/tools", json=builtin_payload("echo_tool"))
    assert clash.status_code == 409
    assert clash.json()["code"] == "TOOL_NAME_CONFLICT"

    updated = await client.put(
        f"/api/tools/{tool['id']}", json=builtin_payload("echo_tool", description="改过描述")
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "改过描述"
    assert updated.json()["createdAt"] == tool["createdAt"]

    assert (await client.delete(f"/api/tools/{tool['id']}")).status_code == 204
    assert (await client.get("/api/tools")).json() == []


async def test_http_tool_requires_url(client):
    response = await client.post("/api/tools", json=http_payload("no_url", url=""))
    assert response.status_code == 400
    assert response.json()["code"] == "TOOL_INVALID"


async def test_test_endpoint_validates_args_and_returns_result(client):
    tool = (await client.post("/api/tools", json=builtin_payload("echo_tool"))).json()

    bad = (
        await client.post(f"/api/tools/{tool['id']}/test", json={"args": {}})
    ).json()
    assert bad["ok"] is False
    assert bad["code"] == "TOOL_ARGS_INVALID"
    assert "text" in bad["error"]

    good = (
        await client.post(f"/api/tools/{tool['id']}/test", json={"args": {"text": "hi"}})
    ).json()
    assert good["ok"] is True
    assert good["result"] == {"echo": "hi"}
    assert good["attempts"] == 1
    assert good["latencyMs"] >= 0


async def test_http_tool_retries_5xx_then_succeeds(client, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True, "n": calls["n"]})

    monkeypatch.setattr(
        tool_runner,
        "_client_factory",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    tool = (await client.post("/api/tools", json=http_payload("flaky", retries=2))).json()

    result = (await client.post(f"/api/tools/{tool['id']}/test", json={"args": {}})).json()
    assert result["ok"] is True
    assert result["attempts"] == 3, "503 要按 retries 重试，第 3 次才成功"
    assert result["httpStatus"] == 200
    assert result["result"] == {"ok": True, "n": 3}


async def test_http_tool_does_not_retry_4xx(client, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad args"})

    monkeypatch.setattr(
        tool_runner,
        "_client_factory",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    tool = (await client.post("/api/tools", json=http_payload("picky", retries=3))).json()

    result = (await client.post(f"/api/tools/{tool['id']}/test", json={"args": {}})).json()
    assert result["ok"] is False
    assert calls["n"] == 1, "4xx 是参数/鉴权问题，重试只会重复挨骂"
    assert result["httpStatus"] == 400
    assert "400" in result["error"]


async def test_idempotency_reuses_previous_success(client, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"hit": calls["n"]})

    monkeypatch.setattr(
        tool_runner,
        "_client_factory",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    tool = (
        await client.post(
            "/api/tools",
            json=http_payload("once", idempotency="key", idempotencyTtlS=600),
        )
    ).json()

    payload = {"args": {"q": "same"}, "useIdempotency": True}
    first = (await client.post(f"/api/tools/{tool['id']}/test", json=payload)).json()
    second = (await client.post(f"/api/tools/{tool['id']}/test", json=payload)).json()

    assert first["idemHit"] is False and first["attempts"] == 1
    assert second["idemHit"] is True, "同参数第二次必须命中缓存"
    assert second["attempts"] == 0
    assert second["result"] == first["result"]
    assert calls["n"] == 1, "整个过程中只能真的打一次网络"


