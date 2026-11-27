"""Agent 持久化：定义整体存 JSON，列表只读冗余列。"""
import uuid

import orjson

from app.database import db
from app.models.agent import Agent, AgentCreate
from app.services.event_bus import utc_now


class AgentNotFound(LookupError):
    pass


def _row_to_agent(row) -> Agent:
    payload = orjson.loads(row["definition_json"])
    return Agent(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        **payload,
    )


async def create_agent(payload: AgentCreate) -> Agent:
    now = utc_now()
    agent = Agent(
        id=f"agent_{uuid.uuid4().hex[:12]}",
        created_at=now,
        updated_at=now,
        **payload.model_dump(by_alias=True),
    )
    await db.execute(
        "INSERT INTO agents (id, name, description, definition_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            agent.id,
            agent.name,
            agent.description,
            orjson.dumps(payload.model_dump(by_alias=True)).decode(),
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
    await db.execute(
        "UPDATE agents SET name = ?, description = ?, definition_json = ?, updated_at = ? WHERE id = ?",
        (payload.name, payload.description, orjson.dumps(definition).decode(), now, agent_id),
    )
    return await get_agent(agent_id)


async def delete_agent(agent_id: str) -> None:
    await get_agent(agent_id)
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
