"""MCP Server 注册表存取（R5）。

`definition_json` 是唯一真相；表内只保留 name / enabled 两列供唯一约束与列表过滤，
transport / command_or_url 不再单独冗余。
"""
import orjson

from app.database import db
from app.models.mcp import MCPServerCreate, MCPServerDef
from app.services.event_bus import utc_now

COLS = "id, name, enabled, definition_json, created_at, updated_at"


class MCPServerNotFound(LookupError):
    pass


class MCPNameConflict(ValueError):
    pass


def _row_to_server(row) -> MCPServerDef:
    return MCPServerDef.model_validate(orjson.loads(row["definition_json"]))


async def list_servers(*, only_enabled: bool = False) -> list[MCPServerDef]:
    sql = f"SELECT {COLS} FROM mcp_servers"
    if only_enabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY name"
    rows = await db.fetchall(sql)
    return [_row_to_server(row) for row in rows]


async def get_server(server_id: str) -> MCPServerDef:
    row = await db.fetchone(f"SELECT {COLS} FROM mcp_servers WHERE id = ?", (server_id,))
    if row is None:
        raise MCPServerNotFound(f"MCP Server 不存在: {server_id}")
    return _row_to_server(row)


async def create_server(payload: MCPServerCreate) -> MCPServerDef:
    clash = await db.fetchone("SELECT id FROM mcp_servers WHERE name = ?", (payload.name,))
    if clash:
        raise MCPNameConflict(f"MCP Server 名称已存在: {payload.name}")

    now = utc_now()
    server = MCPServerDef(
        id=f"mcp_{now[:10].replace('-', '')}_{now[11:19].replace(':', '')}{_rand()}",
        **payload.model_dump(),
    )
    server.created_at = now
    server.updated_at = now
    await db.execute(
        f"INSERT INTO mcp_servers ({COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (
            server.id,
            server.name,
            int(server.enabled),
            orjson.dumps(server.model_dump(mode="json")).decode(),
            now,
            now,
        ),
    )
    return server


async def update_server(server_id: str, payload: MCPServerCreate) -> MCPServerDef:
    existing = await get_server(server_id)
    if payload.name != existing.name:
        clash = await db.fetchone("SELECT id FROM mcp_servers WHERE name = ?", (payload.name,))
        if clash and clash["id"] != server_id:
            raise MCPNameConflict(f"MCP Server 名称已存在: {payload.name}")

    server = MCPServerDef(id=server_id, **payload.model_dump())
    server.created_at = existing.created_at
    server.updated_at = utc_now()
    await db.execute(
        "UPDATE mcp_servers SET name = ?, enabled = ?, definition_json = ?, updated_at = ? "
        "WHERE id = ?",
        (
            server.name,
            int(server.enabled),
            orjson.dumps(server.model_dump(mode="json")).decode(),
            server.updated_at,
            server_id,
        ),
    )
    return server


async def delete_server(server_id: str) -> None:
    deleted = await db.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    if deleted == 0:
        raise MCPServerNotFound(f"MCP Server 不存在: {server_id}")


def _rand() -> str:
    import uuid

    return uuid.uuid4().hex[:4]
