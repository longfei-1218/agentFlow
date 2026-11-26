"""R2-3：手写 Agent Loop 的真实语义（模型调用走确定性桩）。"""
from app.config import settings
from app.services.event_bus import event_bus
from helpers import create_flow, edge, node, wait_for_status


async def _flow(client, nodes, edges, name="loop 用例"):
    return await create_flow(client, nodes, edges, name=name)


async def test_loop_streams_tokens_with_usage_and_steps(client):
    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, model="", system="你是助手", max_tokens=64),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "你好"}})).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})

    history = await event_bus.history(run["id"])
    tokens = [event for event in history if event.type == "token"]
    assert len(tokens) >= 2
    assert all(event.payload["deltaTokens"] > 0 for event in tokens)
    assert "".join(event.payload["text"] for event in tokens) == "你好，这是测试回答。"

    # usage 校准：桩返回 total 9，所以库里应正好是 9，不多不少
    assert final["tokenUsage"] == 9
    assert final["state"]["steps"] == 1
    assert final["state"]["model"] == settings.LLM_DEFAULT_MODEL  # 节点留空时回落到全局默认
    assert final["outputs"]["text"] == "你好，这是测试回答。"
    assert final["costEstimate"] > 0


async def test_prompt_node_interpolates_before_llm(client, monkeypatch):
    from app.services.llm import LLMDelta

    captured: dict = {}

    async def fake_stream(config, messages, *, model=None, temperature=None, max_tokens=None):
        captured["messages"] = messages
        yield LLMDelta(delta_tokens=3, delta_prompt_tokens=3)
        yield LLMDelta(text="cat", delta_tokens=1, delta_completion_tokens=1)
        yield LLMDelta(usage={"promptTokens": 3, "completionTokens": 1, "totalTokens": 4})

    monkeypatch.setattr("app.engine.loop.stream_completion", fake_stream)

    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("prompt_1", "prompt", 120, template="请翻译成英文：{{query}}"),
            node("llm_1", "llm", 240, system="你是翻译", max_tokens=64),
            node("output_1", "output", 360, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "prompt_1"),
            edge("e_2", "prompt_1", "llm_1"),
            edge("e_3", "llm_1", "output_1"),
        ],
        name="prompt 插值",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "猫"}})).json()
    final = await wait_for_status(client, run["id"], {"succeeded"})

    # prompt 节点先把模板写进 variables.text，llm 节点才拿到这句 user 消息
    assert captured["messages"][-1]["content"] == "请翻译成英文：猫"
    assert final["outputs"]["text"] == "cat"


async def test_step_limit_guard_fails_run_without_killing_process(client, monkeypatch):
    """MAX_STEPS=1 时第二个 llm 节点必须被拦下，且进程/后续请求仍然正常。"""
    monkeypatch.setattr(settings, "MAX_STEPS", 1)

    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="第一轮", max_tokens=64),
            node("llm_2", "llm", 400, system="第二轮", max_tokens=64),
            node("output_1", "output", 600, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "llm_1"),
            edge("e_2", "llm_1", "llm_2"),
            edge("e_3", "llm_2", "output_1"),
        ],
        name="步数守卫",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})).json()
    final = await wait_for_status(client, run["id"], {"failed"})

    assert "MAX_STEPS" in final["error"]
    history = await event_bus.history(run["id"])
    failed = [event for event in history if event.type == "run_failed"]
    assert failed and failed[-1].payload.get("code") == "STEP_LIMIT_EXCEEDED"

    # 守卫只拦这一次运行，服务本身必须还能继续接活
    health = await client.get("/api/health")
    assert health.status_code == 200


async def test_run_requires_llm_key_before_creating_run(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是助手"),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="未配置 key",
    )
    response = await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {}})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "LLM_NOT_CONFIGURED"
    assert "系统" in body["message"] or "设置" in body["message"]

    # 没有 llm 节点的流程不依赖模型，照样能跑
    plain = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("output_1", "output", 200, fields=["query"]),
        ],
        [edge("e_1", "input_1", "output_1")],
        name="无模型流程",
    )
    ok = await client.post(f"/api/flows/{plain['id']}/run", json={"inputs": {"query": "hi"}})
    assert ok.status_code == 202


async def test_model_mismatch_error_says_which_model_and_node(client, monkeypatch):
    """网关不认节点里写死的模型时，报错必须自己说清「用了哪个模型、在哪个节点、怎么改」。"""
    from app.services.llm import LLMError

    async def rejecting_stream(config, messages, *, model=None, temperature=None, max_tokens=None):
        raise LLMError(
            f"模型接口返回 400: The supported API model names are deepseek-flash, but you passed {model}.",
            code="LLM_HTTP_ERROR",
        )
        yield  # pragma: no cover —— 只为保持 async generator 形态

    monkeypatch.setattr("app.engine.loop.stream_completion", rejecting_stream)

    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, model="gpt-4o-mini", system="你是助手"),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [edge("e_1", "input_1", "llm_1"), edge("e_2", "llm_1", "output_1")],
        name="模型不匹配",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "hi"}})).json()
    final = await wait_for_status(client, run["id"], {"failed"})

    assert "gpt-4o-mini" in final["error"]
    assert "llm_1" in final["error"]
    assert "清空" in final["error"]
    assert final["state"]["model"] == "gpt-4o-mini"  # 失败的 run 也留得住「当时用的模型」

    history = await event_bus.history(run["id"])
    failed = [event for event in history if event.type == "run_failed"][-1]
    assert failed.payload["code"] == "LLM_HTTP_ERROR"
    assert failed.payload["model"] == "gpt-4o-mini"
    assert failed.payload["nodeId"] == "llm_1"
    assert failed.payload["modelFromNode"] is True


async def test_human_approval_resume_still_works_in_loop(client):
    flow = await _flow(
        client,
        [
            node("input_1", "input", name="query"),
            node("llm_1", "llm", 200, system="你是助手", max_tokens=64),
            node("human_1", "human", 300, message="允许继续？", timeout=300),
            node("output_1", "output", 400, fields=["text"]),
        ],
        [
            edge("e_1", "input_1", "llm_1"),
            edge("e_2", "llm_1", "human_1"),
            edge("e_3", "human_1", "output_1"),
        ],
        name="loop 审批",
    )
    run = (await client.post(f"/api/flows/{flow['id']}/run", json={"inputs": {"query": "x"}})).json()
    await wait_for_status(client, run["id"], {"waiting_human"})

    await client.post(f"/api/runs/{run['id']}/resume", json={"approved": True})
    final = await wait_for_status(client, run["id"], {"succeeded"})
    assert final["outputs"]["text"]
    assert final["state"]["human_pending"] is None
