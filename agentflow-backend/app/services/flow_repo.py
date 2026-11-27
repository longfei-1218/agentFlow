"""Flow 读写：API 层与执行器共用，避免各自拼 SQL。"""
import orjson
from fastapi import HTTPException

from app.database import db
from app.models.flow import Flow
from app.services.version_repo import flow_config_hash


def row_to_flow(row) -> Flow:
    flow = Flow.model_validate(orjson.loads(row["dsl_json"]))
    keys = row.keys()
    updates: dict = {}
    if "version" in keys and row["version"] is not None:
        updates["version"] = int(row["version"])
    if "draft_hash" in keys:
        updates["draft_hash"] = row["draft_hash"]
    if "published_hash" in keys:
        updates["published_hash"] = row["published_hash"]
    return flow.model_copy(update=updates) if updates else flow


async def load_flow(flow_id: str) -> Flow:
    row = await db.fetchone("SELECT * FROM flows WHERE id = ?", (flow_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    return row_to_flow(row)


async def save_flow(flow: Flow, *, bump_version: bool = False) -> Flow:
    """写回 DSL。bump_version=False 时只更新内容，version 保持（草稿自动保存语义）。"""
    version = flow.version + 1 if bump_version else flow.version
    flow = flow.model_copy(update={"version": version})
    draft_hash = flow_config_hash(flow)
    await db.execute(
        "UPDATE flows SET name = ?, version = ?, draft_hash = ?, dsl_json = ?, updated_at = ? "
        "WHERE id = ?",
        (
            flow.name,
            flow.version,
            draft_hash,
            orjson.dumps(
                flow.model_dump(exclude={"draft_hash", "published_hash"})
            ).decode(),
            flow.updated_at,
            flow.id,
        ),
    )
    return flow.model_copy(update={"draft_hash": draft_hash})
