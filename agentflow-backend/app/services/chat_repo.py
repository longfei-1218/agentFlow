"""Agent 会话与聊天轮次：作用域 agent_id + flow_id + node_id。"""
import uuid

import orjson

from app.database import db
from app.models.chat import ChatMessage, ChatTurnResult, Conversation
from app.services.event_bus import utc_now

HISTORY_MAX_TURNS = 6
HISTORY_MAX_CHARS = 3000


class ConversationNotFound(LookupError):
    pass


def answer_text(outputs: dict | None) -> str:
    """从 Agent / end 产物里取一句可展示的回答。"""
    if not outputs:
        return ""
    if not isinstance(outputs, dict):
        return str(outputs)
    for key in ("text", "result", "answer"):
        value = outputs.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for value in outputs.values():
        if isinstance(value, dict):
            nested = answer_text(value)
            if nested:
                return nested
        if isinstance(value, str) and value.strip():
            return value
    return orjson.dumps(outputs, option=orjson.OPT_NON_STR_KEYS).decode()


def _row_to_conversation(row) -> Conversation:
    return Conversation(
        id=row["id"],
        agent_id=row["agent_id"],
        flow_id=row["flow_id"],
        node_id=row["node_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_conversation(
    agent_id: str,
    *,
    flow_id: str | None = None,
    node_id: str | None = None,
    title: str = "",
) -> Conversation:
    now = utc_now()
    conversation = Conversation(
        id=f"conv_{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        flow_id=flow_id,
        node_id=node_id,
        title=title.strip() or "新对话",
        created_at=now,
        updated_at=now,
    )
    await db.execute(
        "INSERT INTO conversations (id, agent_id, flow_id, node_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            conversation.id,
            conversation.agent_id,
            conversation.flow_id,
            conversation.node_id,
            conversation.title,
            conversation.created_at,
            conversation.updated_at,
        ),
    )
    return conversation


async def find_or_create_conversation(
    agent_id: str,
    *,
    flow_id: str | None = None,
    node_id: str | None = None,
    title: str = "",
) -> Conversation:
    sql = "SELECT * FROM conversations WHERE agent_id = ?"
    params: list = [agent_id]
    for column, value in (("flow_id", flow_id), ("node_id", node_id)):
        if value is None:
            sql += f" AND {column} IS NULL"
        else:
            sql += f" AND {column} = ?"
            params.append(value)
    rows = await db.fetchall(sql + " ORDER BY updated_at DESC LIMIT 1", params)
    if rows:
        return _row_to_conversation(rows[0])
    return await create_conversation(
        agent_id, flow_id=flow_id, node_id=node_id, title=title
    )


async def list_conversations(
    agent_id: str | None = None,
    *,
    flow_id: str | None = None,
    node_id: str | None = None,
) -> list[Conversation]:
    where: list[str] = []
    params: list = []
    if agent_id:
        where.append("agent_id = ?")
        params.append(agent_id)
    if flow_id:
        where.append("flow_id = ?")
        params.append(flow_id)
    if node_id:
        where.append("node_id = ?")
        params.append(node_id)
    sql = "SELECT * FROM conversations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC"
    return [_row_to_conversation(row) for row in await db.fetchall(sql, params)]


async def get_conversation(conversation_id: str) -> Conversation:
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise ConversationNotFound(f"会话不存在: {conversation_id}")
    return _row_to_conversation(row)


async def touch_conversation(conversation_id: str, *, title: str | None = None) -> None:
    if title is None:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now(), conversation_id),
        )
    else:
        await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, utc_now(), conversation_id),
        )


async def delete_conversation(conversation_id: str) -> None:
    await get_conversation(conversation_id)
    await db.execute("DELETE FROM chat_turns WHERE conversation_id = ?", (conversation_id,))
    await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


async def add_turn(conversation_id: str, content: str, run_id: str) -> str:
    turn_id = f"turn_{uuid.uuid4().hex[:12]}"
    await db.execute(
        "INSERT INTO chat_turns (id, conversation_id, user_content, run_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (turn_id, conversation_id, content, run_id, utc_now()),
    )
    await touch_conversation(conversation_id)
    return turn_id


async def turn_count(conversation_id: str) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM chat_turns WHERE conversation_id = ?", (conversation_id,)
    )
    return int(row["n"]) if row else 0


async def _turn_rows(conversation_id: str) -> list:
    return await db.fetchall(
        "SELECT t.id AS turn_id, t.user_content, t.run_id, t.created_at, "
        "r.status, r.outputs_json, r.error, r.token_usage, r.cost "
        "FROM chat_turns t LEFT JOIN runs r ON r.id = t.run_id "
        "WHERE t.conversation_id = ? ORDER BY t.created_at ASC, t.id ASC",
        (conversation_id,),
    )


async def conversation_messages(conversation_id: str) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for row in await _turn_rows(conversation_id):
        status = row["status"] or "pending"
        outputs = orjson.loads(row["outputs_json"]) if row["outputs_json"] else None
        content = ""
        error = row["error"]
        if status == "succeeded":
            content = answer_text(outputs)
        elif status in ("failed", "cancelled"):
            content = "运行失败：%s" % (error or "未知错误")
        messages.append(
            ChatMessage(
                id=f"{row['turn_id']}:user",
                role="user",
                content=row["user_content"],
                turn_id=row["turn_id"],
                run_id=row["run_id"],
            )
        )
        if status in ("succeeded", "failed", "cancelled", "running", "pending", "waiting_human"):
            messages.append(
                ChatMessage(
                    id=f"{row['turn_id']}:assistant",
                    role="assistant",
                    content=content,
                    turn_id=row["turn_id"],
                    run_id=row["run_id"],
                    status=status,
                    error=error,
                    tokens=int(row["token_usage"] or 0),
                    cost=float(row["cost"] or 0.0),
                )
            )
    return messages


async def build_history(
    conversation_id: str,
    *,
    max_turns: int = HISTORY_MAX_TURNS,
    max_chars: int = HISTORY_MAX_CHARS,
) -> str:
    parts: list[str] = []
    for row in await _turn_rows(conversation_id):
        if (row["status"] or "") != "succeeded":
            continue
        outputs = orjson.loads(row["outputs_json"]) if row["outputs_json"] else None
        answer = answer_text(outputs).strip()
        if not answer:
            continue
        parts.append(f"用户：{row['user_content']}\n助手：{answer}")

    parts = parts[-max_turns:]
    while len(parts) > 1 and len("\n\n".join(parts)) > max_chars:
        parts.pop(0)
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


async def list_turns(conversation_id: str) -> list[ChatTurnResult]:
    rows = await _turn_rows(conversation_id)
    return [
        ChatTurnResult(
            conversation_id=conversation_id,
            turn_id=row["turn_id"],
            run_id=row["run_id"] or "",
            status=row["status"] or "pending",
        )
        for row in rows
    ]
