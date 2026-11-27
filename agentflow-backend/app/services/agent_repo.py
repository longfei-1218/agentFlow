"""Agent 持久化：定义整体存 JSON，列表只读冗余列。"""
import uuid

import orjson

from app.database import db
from app.models.agent import Agent, AgentCreate
from app.services.event_bus import utc_now
from app.services.version_repo import agent_config_hash


class AgentNotFound(LookupError):
    pass


def _row_to_agent(row) -> Agent:
    payload = orjson.loads(row["definition_json"])
    keys = row.keys()
    return Agent(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=int(row["published_version"] or 0) if "published_version" in keys else 0,
        draft_hash=row["draft_hash"] if "draft_hash" in keys else None,
        published_hash=row["published_hash"] if "published_hash" in keys else None,
        **payload,
    )


async def create_agent(payload: AgentCreate) -> Agent:
    now = utc_now()
    draft_hash = agent_config_hash(payload)
    agent = Agent(
        id=f"agent_{uuid.uuid4().hex[:12]}",
        created_at=now,
        updated_at=now,
        version=0,
        draft_hash=draft_hash,
        published_hash=None,
        **payload.model_dump(by_alias=True),
    )
    await db.execute(
        "INSERT INTO agents (id, name, description, definition_json, published_version, "
        "draft_hash, published_hash, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            agent.id,
            agent.name,
            agent.description,
            orjson.dumps(payload.model_dump(by_alias=True)).decode(),
            0,
            draft_hash,
            None,
            agent.created_at,
            agent.updated_at,
        ),
    )
    return agent


async def list_agents() -> list[Agent]:
    rows = await db.fetchall("SELECT * FROM agents ORDER BY updated_at DESC, id DESC")
    return [_row_to_agent(row) for row in rows]


async def get_agent(agent_id: str) -> Agent:
    row = await db.fetchone("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if row is None:
        raise AgentNotFound(f"Agent 不存在: {agent_id}")
    return _row_to_agent(row)


async def update_agent(agent_id: str, payload: AgentCreate) -> Agent:
    await get_agent(agent_id)
    now = utc_now()
    definition = payload.model_dump(by_alias=True)
    # 草稿指纹变更只影响「是否有未发布改动」，不改变发布指针
    await db.execute(
        "UPDATE agents SET name = ?, description = ?, definition_json = ?, draft_hash = ?, "
        "updated_at = ? WHERE id = ?",
        (
            payload.name,
            payload.description,
            orjson.dumps(definition).decode(),
            agent_config_hash(payload),
            now,
            agent_id,
        ),
    )
    return await get_agent(agent_id)


async def delete_agent(agent_id: str) -> None:
    await get_agent(agent_id)
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
