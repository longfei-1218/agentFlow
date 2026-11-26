"""工具注册表与调用记录的存取（R3）。

存储形态：`tools.definition_json` 存整份 ToolDef（含 timeout/retry/幂等等执行参数），
另外把 name/kind/params_schema/endpoint/risk/enabled 冗余成列，方便列表页 SQL 排序筛选；
冗余列只从 definition 反推，绝不单独维护，避免两套真相。
"""
from typing import Any

import orjson

from app.database import db
from app.models.tool import BUILTIN_SCHEMAS, ToolCreate, ToolDef, ToolInvocation
from app.services.event_bus import utc_now

COLS = (
    "id, name, kind, schema_json, endpoint, risk, enabled, "
    "definition_json, created_at, updated_at"
)


class ToolNotFound(LookupError):
    pass


class ToolNameConflict(ValueError):
    pass


def _row_to_tool(row) -> ToolDef:
    if row["definition_json"]:
        return ToolDef.model_validate(orjson.loads(row["definition_json"]))
    # 兼容旧 `tools` 表里手写的历史行（只有列没有 definition）
    return ToolDef(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        params_schema=orjson.loads(row["schema_json"] or "{}"),
        url=row["endpoint"] or "",
        risk=row["risk"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _normalize(payload: ToolCreate) -> ToolCreate:
    """内置工具的参数 Schema 用注册表里的定义覆盖，避免用户传进来一份不一致的。"""
    if payload.kind == "builtin":
        if not payload.builtin:
            raise ValueError("内置工具必须指定 builtin（echo / now / calc）")
        payload.params_schema = BUILTIN_SCHEMAS[payload.builtin]
        payload.method = "POST"
        payload.url = ""
    else:
        if not payload.url.strip():
            raise ValueError("HTTP 工具必须填 URL")
        payload.method = payload.method.upper()
    return payload


async def list_tools(*, only_enabled: bool = False) -> list[ToolDef]:
    sql = f"SELECT {COLS} FROM tools"
    if only_enabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY created_at"
    rows = await db.fetchall(sql)
    return [_row_to_tool(row) for row in rows]


async def get_tool(tool_id: str) -> ToolDef:
    row = await db.fetchone(f"SELECT {COLS} FROM tools WHERE id = ?", (tool_id,))
    if row is None:
        raise ToolNotFound(f"工具不存在: {tool_id}")
    return _row_to_tool(row)


async def get_tools_by_ids(tool_ids: list[str]) -> list[ToolDef]:
    """按 id 批量取，顺序跟随入参；缺的 id 直接报错，不静默跳过（静默跳过会让模型以为工具可用）。"""
    found: dict[str, ToolDef] = {}
    for tool_id in dict.fromkeys(tool_ids):
        found[tool_id] = await get_tool(tool_id)
    return [found[tool_id] for tool_id in dict.fromkeys(tool_ids)]


async def create_tool(payload: ToolCreate) -> ToolDef:
    payload = _normalize(payload)
    existing = await db.fetchone("SELECT id FROM tools WHERE name = ?", (payload.name,))
    if existing:
        raise ToolNameConflict(f"工具名已存在: {payload.name}")

    now = utc_now()
    tool = ToolDef(id=f"tool_{now[:10].replace('-', '')}_{now[11:19].replace(':', '')}{_rand()}", **payload.model_dump())
    tool.created_at = now
    tool.updated_at = now
    await db.execute(
        f"INSERT INTO tools ({COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tool.id,
            tool.name,
            tool.kind,
            orjson.dumps(tool.params_schema).decode(),
            tool.url or None,
            tool.risk,
            int(tool.enabled),
            orjson.dumps(tool.model_dump()).decode(),
            now,
            now,
        ),
    )
    return tool


async def update_tool(tool_id: str, payload: ToolCreate) -> ToolDef:
    existing = await get_tool(tool_id)
    payload = _normalize(payload)
    if payload.name != existing.name:
        clash = await db.fetchone("SELECT id FROM tools WHERE name = ?", (payload.name,))
        if clash and clash["id"] != tool_id:
            raise ToolNameConflict(f"工具名已存在: {payload.name}")

    tool = ToolDef(id=tool_id, **payload.model_dump())
    tool.created_at = existing.created_at
    tool.updated_at = utc_now()
    await db.execute(
        "UPDATE tools SET name = ?, kind = ?, schema_json = ?, endpoint = ?, risk = ?, "
        "enabled = ?, definition_json = ?, updated_at = ? WHERE id = ?",
        (
            tool.name,
            tool.kind,
            orjson.dumps(tool.params_schema).decode(),
            tool.url or None,
            tool.risk,
            int(tool.enabled),
            orjson.dumps(tool.model_dump()).decode(),
            tool.updated_at,
            tool_id,
        ),
    )
    return tool


async def delete_tool(tool_id: str) -> None:
    deleted = await db.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    if deleted == 0:
        raise ToolNotFound(f"工具不存在: {tool_id}")
    await db.execute("DELETE FROM tool_invocations WHERE tool_id = ?", (tool_id,))


def _rand() -> str:
    import uuid

    return uuid.uuid4().hex[:4]


async def record_invocation(invocation: ToolInvocation) -> ToolInvocation:
    invocation.created_at = invocation.created_at or utc_now()
    await db.execute(
        "INSERT INTO tool_invocations (id, tool_id, tool_name, run_id, node_id, args_json, "
        "status, attempts, latency_ms, http_status, result_json, error, idem_key, idem_hit, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invocation.id,
            invocation.tool_id,
            invocation.tool_name,
            invocation.run_id,
            invocation.node_id,
            orjson.dumps(invocation.args).decode(),
            invocation.status,
            invocation.attempts,
            invocation.latency_ms,
            invocation.http_status,
            None if invocation.result is None else orjson.dumps(invocation.result).decode(),
            invocation.error,
            invocation.idem_key,
            int(invocation.idem_hit),
            invocation.created_at,
        ),
    )
    return invocation


def _row_to_invocation(row) -> ToolInvocation:
    return ToolInvocation(
        id=row["id"],
        tool_id=row["tool_id"],
        tool_name=row["tool_name"],
        run_id=row["run_id"],
        node_id=row["node_id"],
        args=orjson.loads(row["args_json"] or "{}"),
        status=row["status"],
        attempts=row["attempts"],
        latency_ms=row["latency_ms"],
        http_status=row["http_status"],
        result=None if row["result_json"] is None else orjson.loads(row["result_json"]),
        error=row["error"],
        idem_key=row["idem_key"],
        idem_hit=bool(row["idem_hit"]),
        created_at=row["created_at"],
    )


async def list_invocations(
    *, tool_id: str | None = None, limit: int = 20
) -> list[ToolInvocation]:
    sql = "SELECT * FROM tool_invocations"
    params: list[Any] = []
    if tool_id:
        sql += " WHERE tool_id = ?"
        params.append(tool_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 100)))
    rows = await db.fetchall(sql, params)
    return [_row_to_invocation(row) for row in rows]


async def find_recent_ok_by_idem(idem_key: str, since_iso: str) -> ToolInvocation | None:
    row = await db.fetchone(
        "SELECT * FROM tool_invocations WHERE idem_key = ? AND status = 'ok' "
        "AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
        (idem_key, since_iso),
    )
    return None if row is None else _row_to_invocation(row)
