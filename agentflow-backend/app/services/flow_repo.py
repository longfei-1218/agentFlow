"""Flow 读写：API 层与执行器共用，避免各自拼 SQL。"""
import orjson
from fastapi import HTTPException

from app.database import db
from app.models.flow import Flow


def row_to_flow(row) -> Flow:
    return Flow.model_validate(orjson.loads(row["dsl_json"]))


async def load_flow(flow_id: str) -> Flow:
    row = await db.fetchone("SELECT dsl_json FROM flows WHERE id = ?", (flow_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"流程不存在: {flow_id}")
    return row_to_flow(row)


async def save_flow(flow: Flow, *, bump_version: bool = False) -> Flow:
    """写回 DSL。bump_version=False 时只更新内容，version 保持（草稿自动保存语义）。"""
    version = flow.version + 1 if bump_version else flow.version
    flow = flow.model_copy(update={"version": version})
    await db.execute(
        "UPDATE flows SET name = ?, version = ?, dsl_json = ?, updated_at = ? WHERE id = ?",
        (
            flow.name,
            flow.version,
            orjson.dumps(flow.model_dump()).decode(),
            flow.updated_at,
            flow.id,
        ),
    )
    return flow
