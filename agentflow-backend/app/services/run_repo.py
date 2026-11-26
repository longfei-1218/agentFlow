"""Run 读写：列白名单 + 状态聚合，执行器与 API 共用。"""
import orjson
from fastapi import HTTPException

from app.database import db
from app.models.run import Run, RunStatus

TERMINAL_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}

# 只允许这些列被 update_run 写入，防止执行器误改主键等字段
WRITABLE_FIELDS = {
    "status",
    "outputs_json",
    "state_json",
    "error",
    "token_usage",
    "cost",
    "started_at",
    "finished_at",
}


def row_to_run(row) -> Run:
    return Run(
        id=row["id"],
        flow_id=row["flow_id"],
        flow_version=row["flow_version"],
        status=RunStatus(row["status"]),
        inputs=orjson.loads(row["inputs_json"]),
        outputs=orjson.loads(row["outputs_json"]) if row["outputs_json"] else None,
        state=orjson.loads(row["state_json"] or "{}"),
        error=row["error"],
        token_usage=row["token_usage"],
        cost_estimate=row["cost"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def load_run(run_id: str) -> Run:
    row = await db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"运行不存在: {run_id}")
    return row_to_run(row)


async def update_run(run_id: str, **fields) -> None:
    unknown = set(fields) - WRITABLE_FIELDS
    if unknown:
        raise ValueError(f"不允许写入的列: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    await db.execute(
        f"UPDATE runs SET {assignments} WHERE id = ?",
        [*fields.values(), run_id],
    )


async def max_seq(run_id: str) -> int:
    """已落库的最大事件序号：服务重启后续发事件必须从这里接着走，否则撞主键。"""
    row = await db.fetchone("SELECT MAX(seq) AS m FROM run_events WHERE run_id = ?", (run_id,))
    return int(row["m"]) if row and row["m"] is not None else 0
