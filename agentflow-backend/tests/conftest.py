"""测试夹具：每个用例一套临时 SQLite，避免互相污染。"""
import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.database import db
from app.main import app
from app.services.event_bus import event_bus


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


@pytest.fixture
def slow_demo(monkeypatch):
    """把演示执行器每步延迟调大，方便在取消/审批之间插入断言。"""
    monkeypatch.setattr(settings, "DEMO_STEP_DELAY", 0.35)
