"""测试夹具：每个用例一套临时 SQLite，避免互相污染。"""
import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.database import db
from app.main import app
from app.services.event_bus import event_bus
from app.services.llm import LLMDelta


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    await db.close()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "agentflow.db"))
    await db.connect()
    event_bus._seq.clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    await db.close()
    event_bus._seq.clear()


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """默认把模型换成确定性桩：测试不打网络、不花 token。

    loop.py 是 `from ... import stream_completion`，所以补丁必须打在执行器模块上，
    打 app.services.llm 是无效的（这点踩过）。
    """
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test-1234567890abcdef")
    monkeypatch.setattr(settings, "RUNNER", "loop")

    async def fake_stream(config, messages, *, model=None, temperature=None, max_tokens=None):
        yield LLMDelta(delta_tokens=5, delta_prompt_tokens=5, cost=0.00001)
        for piece in ("你好，", "这是测试回答。"):
            yield LLMDelta(text=piece, delta_tokens=2, delta_completion_tokens=2, cost=0.00002)
        yield LLMDelta(
            usage={"promptTokens": 5, "completionTokens": 4, "totalTokens": 9, "estimated": False}
        )

    monkeypatch.setattr("app.engine.loop.stream_completion", fake_stream)


@pytest.fixture
def slow_demo(monkeypatch):
    """把节点间停顿调大，方便在取消/审批之间插入断言。"""
    monkeypatch.setattr(settings, "DEMO_STEP_DELAY", 0.35)
