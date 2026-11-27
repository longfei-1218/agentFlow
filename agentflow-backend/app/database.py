"""SQLite 异步访问层：单连接 + 写锁。

设计取舍：
- aiosqlite 每个连接独占一个工作线程，同一连接上的操作天然串行，读操作不需要额外加锁；
- 但事务语义是「连接级」的：两个任务并发 execute+commit 会互相提交对方的中间状态，
  所以所有写操作必须经由 transaction() 或 execute()，由同一把写锁串行化；
- 每次 emit 事件都新开连接会让一个 run 产生几十次 connect+commit，与 runs 表更新争 WAL 写锁，
  这也是改成共享连接的直接原因。
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.config import settings

INIT_SQL = Path(__file__).parent / "db" / "init.sql"


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        path = Path(settings.DATABASE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 5000")
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(INIT_SQL.read_text(encoding="utf-8"))
        await _migrate(conn)
        await conn.commit()
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("数据库尚未初始化，请先调用 init_db()")
        return self._conn

    async def fetchone(self, sql: str, params: tuple | list = ()) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(sql, params)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetchall(self, sql: str, params: tuple | list = ()) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(sql, params)
        try:
            return list(await cursor.fetchall())
        finally:
            await cursor.close()

    async def execute(self, sql: str, params: tuple | list = ()) -> int:
        """单条语句自动提交，返回受影响行数。"""
        async with self._write_lock:
            cursor = await self.conn.execute(sql, params)
            try:
                rowcount = cursor.rowcount
            finally:
                await cursor.close()
            await self.conn.commit()
            return rowcount

    async def execute_many(self, sql: str, params_list: list[tuple | list]) -> None:
        async with self._write_lock:
            await self.conn.executemany(sql, params_list)
            await self.conn.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """多条语句原子提交（读改写、先查后插等场景）。"""
        async with self._write_lock:
            try:
                yield self.conn
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise


db = Database()


async def _ensure_columns(
    conn: aiosqlite.Connection, table: str, additions: dict[str, str]
) -> set[str]:
    """给已存在的老表补列，返回「补列之前」的列名集合（用于判断要不要回填数据）。"""
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    try:
        existing = {row[1] for row in await cursor.fetchall()}
    finally:
        await cursor.close()

    for name, ddl in additions.items():
        if name not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    return existing


async def _migrate(conn: aiosqlite.Connection) -> None:
    """就地补列：CREATE TABLE IF NOT EXISTS 不会给已存在的旧表加字段。

    R3 给 `tools` 加了 definition_json / created_at / updated_at；
    R5 又给 `mcp_servers` / `knowledge_bases` 补了 definition_json 与时间戳。
    老库不用删，连上来自动补齐即可。
    """
    old_columns = await _ensure_columns(
        conn,
        "tools",
        {
            "definition_json": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )
    # 老行没有时间戳：补一个，列表排序才不会把历史工具顶到最前面
    if "created_at" not in old_columns:
        await conn.execute("UPDATE tools SET created_at = '2026-01-01T00:00:00+00:00' WHERE created_at IS NULL")
        await conn.execute("UPDATE tools SET updated_at = created_at WHERE updated_at IS NULL")

    await _ensure_columns(
        conn,
        "mcp_servers",
        {
            "definition_json": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )

    await _ensure_columns(
        conn,
        "knowledge_bases",
        {"created_at": "TEXT", "updated_at": "TEXT"},
    )

    # R5.1 对话模式：老库的 runs 没有会话归属，补列不删历史
    await _ensure_columns(conn, "runs", {"conversation_id": "TEXT"})


async def get_db() -> aiosqlite.Connection:
    """兼容旧调用：返回共享连接。写操作请改用 db.execute / db.transaction。"""
    return db.conn


async def init_db() -> None:
    await db.connect()
