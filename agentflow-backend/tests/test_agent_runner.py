"""AgentRunner：变量渲染、强制工具、输出 schema。"""
from types import SimpleNamespace

import pytest

from app.engine import agent_runner
from app.models.agent import Agent, AgentCreate
from app.services.llm import LLMConfig, LLMDelta

CONFIG = LLMConfig(base_url="http://test", api_key="sk-test", model="fake-model")


def make_agent(**overrides) -> Agent:
    payload = {
        "name": "测试",
        "prompt": {"system": "你是助手", "template": "回答：{{query}}"},
        "variables": [{"key": "query", "type": "string"}],
    }
    payload.update(overrides)
    return Agent(
        id="agent_test",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        **AgentCreate(**payload).model_dump(by_alias=True),
    )


def fake_text_stream(answer: str = "你好。"):
    async def stream(config, messages, **kwargs):
        yield LLMDelta(delta_tokens=3, delta_prompt_tokens=3, cost=0.00001)
        yield LLMDelta(text=answer, delta_tokens=2, delta_completion_tokens=2, cost=0.00002)
        yield LLMDelta(usage={"totalTokens": 5})

    return stream


@pytest.mark.asyncio
async def test_run_agent_renders_variables(monkeypatch):
    captured: list[list[dict]] = []

    async def stream(config, messages, **kwargs):
        captured.append(messages)
        yield LLMDelta(text="收到了。", delta_tokens=2, delta_completion_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    result = await agent_runner.run_agent(
        make_agent(), {"query": "今天天气"}, llm_config=CONFIG
    )
    assert result.outputs == {"text": "收到了。"}
    assert captured[0][0]["role"] == "system"
    assert "回答：今天天气" in captured[0][1]["content"]


@pytest.mark.asyncio
async def test_run_agent_forces_tool_and_feeds_result_back(monkeypatch):
    tool = SimpleNamespace(
        id="tool_echo",
        name="echo",
        description="回显",
        params_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        enabled=True,
    )

    async def get_tool(tool_id: str):
        assert tool_id == "tool_echo"
        return tool

    async def invoke(tool_arg, args, **kwargs):
        assert args == {"text": "hi"}
        return SimpleNamespace(result="echo:hi", latency_ms=4)

    calls = {"n": 0}

    async def stream(config, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            assert kwargs["tool_choice"] == {
                "type": "function",
                "function": {"name": "tool_echo"},
            }
            yield LLMDelta(
                tool_calls=[
                    {"id": "call_1", "name": "tool_echo", "arguments": '{"text":"hi"}'}
                ]
            )
            return
        yield LLMDelta(text="工具结果已收到。", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.tool_repo, "get_tool", get_tool)
    monkeypatch.setattr(agent_runner.tool_runner, "invoke", invoke)
    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)

    agent = make_agent(
        prompt={"system": "", "template": "{{query}} 然后 @tool[echo]"},
        resources=[{"kind": "tool", "id": "tool_echo", "alias": "echo"}],
    )
    result = await agent_runner.run_agent(agent, {"query": "开始"}, llm_config=CONFIG)
    assert result.text == "工具结果已收到。"
    assert result.tool_calls[0]["tool"] == "echo"
    assert result.tool_calls[0]["ok"] is True


@pytest.mark.asyncio
async def test_run_agent_retries_output_schema_once(monkeypatch):
    calls = {"n": 0}

    async def stream(config, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield LLMDelta(text="这不是 JSON", delta_tokens=2, cost=0.00001)
            return
        yield LLMDelta(text='{"text":"合法输出"}', delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    agent = make_agent(
        output={
            "schema": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            }
        }
    )
    result = await agent_runner.run_agent(agent, {"query": "开始"}, llm_config=CONFIG)
    assert calls["n"] == 2
    assert result.outputs == {"text": "合法输出"}


@pytest.mark.asyncio
async def test_run_agent_raises_on_empty_answer(monkeypatch):
    async def stream(config, messages, **kwargs):
        yield LLMDelta(reasoning="我想了很久", delta_tokens=50, cost=0.0001)
        yield LLMDelta(finish_reason="length")

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    with pytest.raises(agent_runner.AgentRunError) as exc:
        await agent_runner.run_agent(make_agent(), {"query": "开始"}, llm_config=CONFIG)
    assert exc.value.code == "AGENT_EMPTY_ANSWER"
    assert "maxTokens" in str(exc.value)


@pytest.mark.asyncio
async def test_run_agent_raises_when_schema_still_invalid(monkeypatch):
    async def stream(config, messages, **kwargs):
        yield LLMDelta(text="还是不是 JSON", delta_tokens=2, cost=0.00001)

    monkeypatch.setattr(agent_runner.llm, "stream_completion", stream)
    agent = make_agent(output={"schema": {"type": "object", "required": ["text"]}})
    with pytest.raises(agent_runner.AgentRunError) as exc:
        await agent_runner.run_agent(agent, {"query": "开始"}, llm_config=CONFIG)
    assert exc.value.code == "AGENT_OUTPUT_INVALID"
