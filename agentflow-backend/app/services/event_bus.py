"""SSE 事件总线：一个 run_id 一个频道，支持多订阅者。

执行引擎写入 -> 先落 run_events 表 -> 再推给所有订阅队列。
SSE 路由按 seq 排序去重，断线重连时从 Last-Event-ID 续推。

序号规则：
- 内存里缓存每个 run 的 seq 游标，避免每次都查库；
- 缓存未命中时从 run_events 的 MAX(seq) 恢复，服务重启后不会从 1 重发撞主键。
"""
import asyncio
from datetime import datetime, timezone

import orjson

from app.database import db
from app.models.run import EventType, RunEvent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = {}
        self._seq: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def register(self, run_id: str) -> asyncio.Queue[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unregister(self, run_id: str, queue: asyncio.Queue[RunEvent]) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(run_id, None)

    async def _ensure_seq(self, run_id: str) -> int:
        """缓存未命中时从数据库恢复游标（调用方需持有 self._lock）。"""
        cached = self._seq.get(run_id)
        if cached is not None:
            return cached
        row = await db.fetchone(
            "SELECT MAX(seq) AS m FROM run_events WHERE run_id = ?", (run_id,)
        )
        current = int(row["m"]) if row and row["m"] is not None else 0
        self._seq[run_id] = current
        return current

    async def emit(
        self,
        run_id: str,
        event_type: EventType,
        node_id: str | None = None,
        payload: dict | None = None,
    ) -> RunEvent:
        async with self._lock:
            await self._ensure_seq(run_id)
            seq = self._seq[run_id] + 1
            self._seq[run_id] = seq

        event = RunEvent(
            id=f"ev_{run_id}_{seq}",
            run_id=run_id,
            seq=seq,
            type=event_type,
            node_id=node_id,
            payload=payload or {},
            created_at=utc_now(),
        )

        await db.execute(
            "INSERT INTO run_events (run_id, seq, type, node_id, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                event.type,
                node_id,
                orjson.dumps(event.payload).decode(),
                event.created_at,
            ),
        )

        for queue in list(self._subscribers.get(run_id, ())):
            queue.put_nowait(event)
        return event

    async def history(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        rows = await db.fetchall(
            "SELECT run_id, seq, type, node_id, payload_json, created_at "
            "FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )
        return [
            RunEvent(
                id=f"ev_{row['run_id']}_{row['seq']}",
                run_id=row["run_id"],
                seq=row["seq"],
                type=row["type"],
                node_id=row["node_id"],
                payload=orjson.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def seed_seq(self, run_id: str, seq: int) -> None:
        """显式设置游标（新 run 传 0；续跑前传 MAX(seq)）。"""
        self._seq[run_id] = max(self._seq.get(run_id, 0), seq)


event_bus = EventBus()
