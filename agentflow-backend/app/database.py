"""SQLite 异步连接与建表。

约定：每个请求/后台任务独占一个 connection；aiosqlite 的连接不可跨任务共享游标。
"""
from pathlib import Path

import aiosqlite

from app.config import settings

INIT_SQL = Path(__file__).parent / "db" / "init.sql"


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db() -> None:
    path = Path(settings.DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.executescript(INIT_SQL.read_text(encoding="utf-8"))
        await db.commit()
