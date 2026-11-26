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


async def test_tool_node_executes_for_real(client):
    tool = (await client.post("/api/tools", json=builtin_payload("echo_tool"))).json()
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("tool_1", "tool", 200, tool_id=tool["id"], args_template='{"text":"{{query}}"}'),
            node("output_1", "output", 400, fields=["result"]),
        ],
        [edge("e_1", "input_1", "tool_1"), edge("e_2", "tool_1", "output_1")],
        name="工具节点",
    )
    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "ping"}})
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})

    assert final["outputs"]["result"] == '{"echo":"ping"}'
    assert final["state"]["tool_calls"][0]["tool"] == "echo_tool"

    history = await event_bus.history(run["id"])
    call_event = next(event for event in history if event.type == "tool_call")
    result_event = next(event for event in history if event.type == "tool_result")
    assert call_event.payload["args"] == {"text": "ping"}
    assert call_event.payload["source"] == "node"
    assert result_event.payload["ok"] is True
    assert result_event.payload.get("stub") is None, "R3 之后不允许再出现占位标记"

    invocations = (await client.get(f"/api/tools/invocations?toolId={tool['id']}")).json()
    assert invocations[0]["runId"] == run["id"]
    assert invocations[0]["nodeId"] == "tool_1"


async def test_state_does_not_leak_between_runs(client):
    """两次 run 的 state 必须相互独立：DEFAULT_STATE 里的 list 曾经被浅拷贝共享过一次。"""
    tool = (await client.post("/api/tools", json=builtin_payload("echo_tool"))).json()
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("tool_1", "tool", 200, tool_id=tool["id"], args_template='{"text":"{{query}}"}'),
            node("output_1", "output", 400, fields=["result"]),
        ],
        [edge("e_1", "input_1", "tool_1"), edge("e_2", "tool_1", "output_1")],
        name="state 隔离",
    )
    first = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "one"}})
    ).json()
    await wait_for_status(client, first["id"], {"succeeded"})
    second = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "two"}})
    ).json()
    final = await wait_for_status(client, second["id"], {"succeeded"})

    assert len(final["state"]["tool_calls"]) == 1, "第二次 run 只能有自己那一次调用"
    assert final["state"]["tool_calls"][0]["args"] == {"text": "two"}


async def test_tool_node_with_missing_tool_fails_run_readably(client):
    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("tool_1", "tool", 200, tool_id="tool_nope", args_template="{}"),
            node("output_1", "output", 400, fields=["result"]),
        ],
        [edge("e_1", "input_1", "tool_1"), edge("e_2", "tool_1", "output_1")],
        name="工具不存在",
    )
    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})
    ).json()
    final = await wait_for_status(client, run["id"], {"failed"})

    assert "工具不存在" in final["error"]
    history = await event_bus.history(run["id"])
    failed = [event for event in history if event.type == "run_failed"][-1]
    assert failed.payload["code"] == "TOOL_NOT_FOUND"
    assert failed.payload["nodeId"] == "tool_1"


async def test_fc_loop_calls_tool_then_answers(client, monkeypatch):
    """模型自己决定调工具：第一轮返回 tool_calls，执行后把结果回填，第二轮给最终答案。"""
    tool = (await client.post("/api/tools", json=builtin_payload("echo_tool"))).json()
    calls = {"n": 0}

    async def fake_stream(config, messages, *, model=None, temperature=None, max_tokens=None, tools=None):
        calls["n"] += 1
        assert tools and tools[0]["function"]["name"] == "echo_tool", "绑定的工具必须进请求体"
        if calls["n"] == 1:
            yield LLMDelta(delta_tokens=5, delta_prompt_tokens=5, cost=0.00001)
            yield LLMDelta(
                tool_calls=[{"id": "call_1", "name": "echo_tool", "arguments": '{"text":"ping"}'}]
            )
            yield LLMDelta(usage={"promptTokens": 5, "completionTokens": 2, "totalTokens": 7})
        else:
            assert any(
                message.get("role") == "tool" and "ping" in str(message.get("content"))
                for message in messages
            ), "执行结果必须作为 tool 消息回填"
            yield LLMDelta(text="工具说 ping", delta_tokens=3, delta_completion_tokens=3)
            yield LLMDelta(usage={"promptTokens": 9, "completionTokens": 3, "totalTokens": 12})

    monkeypatch.setattr("app.engine.loop.stream_completion", fake_stream)

    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是助手", tool_ids=[tool["id"]], max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="FC 回路",
    )
    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "打一下 echo"}})
    ).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})

    assert final["outputs"]["text"] == "工具说 ping"
    assert final["state"]["steps"] == 2, "两轮模型调用 = 2 步"
    assert final["state"]["tool_calls"][0]["tool"] == "echo_tool"

    history = await event_bus.history(run["id"])
    tool_call = next(event for event in history if event.type == "tool_call")
    tool_result = next(event for event in history if event.type == "tool_result")
    assert tool_call.payload["source"] == "llm"
    assert tool_call.payload["callId"] == "call_1"
    assert tool_result.payload["result"] == {"echo": "ping"}

    invocations = (await client.get(f"/api/tools/invocations?toolId={tool['id']}")).json()
    assert invocations[0]["runId"] == run["id"]
    assert invocations[0]["nodeId"] == "llm_1"


async def test_fc_rounds_are_counted_against_max_steps(client, monkeypatch):
    """FC 多轮必须逐轮计数：MAX_STEPS=1 时第二轮就被拦，不能因为「只进了一个节点」放行。"""
    from app.config import settings

    tool = (await client.post("/api/tools", json=builtin_payload("echo_tool"))).json()
    monkeypatch.setattr(settings, "MAX_STEPS", 1)

    async def always_calls(config, messages, *, model=None, temperature=None, max_tokens=None, tools=None):
        yield LLMDelta(delta_tokens=5, delta_prompt_tokens=5)
        yield LLMDelta(
            tool_calls=[{"id": "call_x", "name": "echo_tool", "arguments": '{"text":"again"}'}]
        )

    monkeypatch.setattr("app.engine.loop.stream_completion", always_calls)

    flow = await create_flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是助手", tool_ids=[tool["id"]], max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="FC 步数守卫",
    )
    run = (
        await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "loop"}})
    ).json()
    final = await wait_for_status(client, run["id"], {"failed"})

    assert "MAX_STEPS" in final["error"]
    assert "1 轮工具调用" in final["error"], "错误要说清工具已经调过几轮"
    history = await event_bus.history(run["id"])
    failed = [event for event in history if event.type == "run_failed"][-1]
    assert failed.payload["code"] == "STEP_LIMIT_EXCEEDED"
