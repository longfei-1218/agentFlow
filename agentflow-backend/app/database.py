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
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(INIT_SQL.read_text(encoding="utf-8"))
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


async def get_db() -> aiosqlite.Connection:
    """兼容旧调用：返回共享连接。写操作请改用 db.execute / db.transaction。"""
    return db.conn


async def init_db() -> None:
    await db.connect()
