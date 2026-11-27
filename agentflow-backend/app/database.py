"""SQLite 异步访问层：单连接 + 写锁。

设计取舍：
- aiosqlite 每个连接独占一个工作线程，同一连接上的操作天然串行，读操作不需要额外加锁；
- 但事务语义是「连接级」的：两个任务并发 execute+commit 会互相提交对方的中间状态，
  所以所有写操作必须经由 transaction() 或 execute()，由同一把写锁串行化；
- 每次 emit 事件都新开连接会让一个 run 产生几十次 connect+commit，与 runs 表更新争 WAL 写锁，
  这也是改成共享连接的直接原因。
"""
import asyncio
import json
import sqlite3
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


async def _column_names(conn: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    try:
        return {row[1] for row in await cursor.fetchall()}
    finally:
        await cursor.close()


async def _ensure_columns(
    conn: aiosqlite.Connection, table: str, additions: dict[str, str]
) -> set[str]:
    """给已存在的老表补列，返回「补列之前」的列名集合（用于判断要不要回填数据）。"""
    existing = await _column_names(conn, table)

    for name, ddl in additions.items():
        if name not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    return existing


async def _drop_columns(conn: aiosqlite.Connection, table: str, columns: set[str]) -> None:
    """删除历史冗余列；SQLite 3.35+ 才支持 DROP COLUMN。"""
    if sqlite3.sqlite_version_info < (3, 35, 0):
        return
    existing = await _column_names(conn, table)
    for name in columns:
        if name in existing:
            await conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


async def _backfill_legacy_resource_definitions(conn: aiosqlite.Connection) -> None:
    """删除冗余列之前，把只有列、没有 definition_json 的历史行补成完整定义。

    正常库（R3+ 之后）definition_json 都有值；这里只兜底极老的手写行。
    """
    tool_columns = await _column_names(conn, "tools")
    if {"definition_json", "schema_json"} <= tool_columns:
        cursor = await conn.execute(
            "SELECT id, name, kind, schema_json, endpoint, risk, enabled, created_at, updated_at "
            "FROM tools WHERE definition_json IS NULL"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        for row in rows:
            payload = {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "params_schema": json.loads(row[3] or "{}"),
                "url": row[4] or "",
                "risk": row[5],
                "enabled": bool(row[6]),
                "created_at": row[7],
                "updated_at": row[8],
            }
            await conn.execute(
                "UPDATE tools SET definition_json = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), row[0]),
            )

    mcp_columns = await _column_names(conn, "mcp_servers")
    if {"definition_json", "transport", "command_or_url"} <= mcp_columns:
        cursor = await conn.execute(
            "SELECT id, name, transport, command_or_url, enabled, created_at, updated_at "
            "FROM mcp_servers WHERE definition_json IS NULL"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        for row in rows:
            payload = {
                "id": row[0],
                "name": row[1],
                "transport": row[2],
                "command": "" if row[2] == "http" else (row[3] or ""),
                "url": (row[3] or "") if row[2] == "http" else "",
                "enabled": bool(row[4]),
                "created_at": row[5],
                "updated_at": row[6],
            }
            await conn.execute(
                "UPDATE mcp_servers SET definition_json = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), row[0]),
            )


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

    # R6.0 版本管理：草稿指纹 / 发布指针 / 运行期版本清单
    await _ensure_columns(
        conn,
        "agents",
        {
            "published_version": "INTEGER NOT NULL DEFAULT 0",
            "draft_hash": "TEXT",
            "published_hash": "TEXT",
        },
    )
    await _ensure_columns(
        conn,
        "flows",
        {
            "draft_hash": "TEXT",
            "published_hash": "TEXT",
        },
    )
    await _ensure_columns(
        conn,
        "runs",
        {
            "target_version": "INTEGER NOT NULL DEFAULT 0",
            "version_mode": "TEXT NOT NULL DEFAULT 'published'",
            "manifest_json": "TEXT",
        },
    )
    # 版本名：发布时必填；老版本行留空，前端回退显示 vN
    await _ensure_columns(conn, "agent_versions", {"name": "TEXT NOT NULL DEFAULT ''"})
    await _ensure_columns(conn, "flow_versions", {"name": "TEXT NOT NULL DEFAULT ''"})

    # 清理两次架构变迁留下的冗余：run 旧版本列、资源表只写不查的列、两张空评测表
    runs_columns = await _column_names(conn, "runs")
    if "flow_version" in runs_columns:
        # 先把老 flow run 的发布版本回填到 target_version，再物理删列
        await conn.execute(
            "UPDATE runs SET target_version = flow_version "
            "WHERE target_type = 'flow' AND target_version = 0 AND flow_version > 0"
        )
        await _drop_columns(conn, "runs", {"flow_version"})

    await _backfill_legacy_resource_definitions(conn)
    await _drop_columns(conn, "tools", {"kind", "schema_json", "endpoint", "risk"})
    await _drop_columns(conn, "mcp_servers", {"transport", "command_or_url"})

    # eval_results / eval_trials 零数据、零读写；R6 按实际指标重建
    await conn.execute("DROP TABLE IF EXISTS eval_trials")
    await conn.execute("DROP TABLE IF EXISTS eval_results")


async def init_db() -> None:
    await db.connect()
    # 版本表就绪后再登记老数据基线；这里延迟导入，避免 database ↔ version_repo 循环
    from app.services.version_repo import backfill_baselines

    await backfill_baselines()
