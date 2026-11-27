"""知识库存取与检索（R5）。

数据模型：知识库 → 文档 → 切片。切片是检索的最小单位，检索时一次性把该库的切片读进内存
（本地原型的数据量在几千块以内，比维护倒排索引简单得多；真到十万级再换 FTS/向量库）。
"""
import orjson

from app.database import db
from app.models.knowledge import (
    KBHit,
    KBDocument,
    KBDocumentCreate,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KBSearchResult,
)
from app.resources import knowledge_store
from app.services import knowledge_rag
from app.services.event_bus import utc_now


class KBNotFound(LookupError):
    pass


class KBNameConflict(ValueError):
    pass


class KBDocumentNotFound(LookupError):
    pass


def _row_to_kb(row) -> KnowledgeBase:
    return KnowledgeBase(
        id=row["id"],
        name=row["name"],
        collection=row["collection"],
        chunk_size=row["chunk_size"],
        overlap=row["overlap"],
        embedding_model=row["embedding_model"],
        doc_count=row["doc_count"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"] if "created_at" in row.keys() else None,
        updated_at=row["updated_at"] if "updated_at" in row.keys() else None,
    )


async def list_kbs() -> list[KnowledgeBase]:
    rows = await db.fetchall("SELECT * FROM knowledge_bases ORDER BY created_at, name")
    items = [_row_to_kb(row) for row in rows]
    # 老库第一次被列出时补一份资源目录 manifest，之后文档就有了可读的源文件
    for kb in items:
        try:
            knowledge_store.ensure_kb(kb)
        except OSError:
            pass
    return items


async def get_kb(kb_id: str) -> KnowledgeBase:
    row = await db.fetchone("SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,))
    if row is None:
        raise KBNotFound(f"知识库不存在: {kb_id}")
    return _row_to_kb(row)


async def create_kb(payload: KnowledgeBaseCreate) -> KnowledgeBase:
    clash = await db.fetchone("SELECT id FROM knowledge_bases WHERE name = ?", (payload.name,))
    if clash:
        raise KBNameConflict(f"知识库名称已存在: {payload.name}")

    now = utc_now()
    kb = KnowledgeBase(
        id=f"kb_{now[:10].replace('-', '')}_{now[11:19].replace(':', '')}{_rand()}",
        name=payload.name,
        collection=f"kb_{now[:10].replace('-', '')}_{_rand()}",
        chunk_size=payload.chunk_size,
        overlap=payload.overlap,
        embedding_model=payload.embedding_model,
        created_at=now,
        updated_at=now,
    )
    await db.execute(
        "INSERT INTO knowledge_bases (id, name, collection, chunk_size, overlap, embedding_model, "
        "doc_count, chunk_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kb.id,
            kb.name,
            kb.collection,
            kb.chunk_size,
            kb.overlap,
            kb.embedding_model,
            0,
            0,
            now,
            now,
        ),
    )
    try:
        knowledge_store.ensure_kb(kb)
    except OSError:
        pass
    return kb


async def update_kb(kb_id: str, payload: KnowledgeBaseCreate) -> KnowledgeBase:
    existing = await get_kb(kb_id)
    if payload.name != existing.name:
        clash = await db.fetchone("SELECT id FROM knowledge_bases WHERE name = ?", (payload.name,))
        if clash and clash["id"] != kb_id:
            raise KBNameConflict(f"知识库名称已存在: {payload.name}")
    now = utc_now()
    await db.execute(
        "UPDATE knowledge_bases SET name = ?, chunk_size = ?, overlap = ? WHERE id = ?",
        (payload.name, payload.chunk_size, payload.overlap, kb_id),
    )
    return await get_kb(kb_id)


async def delete_kb(kb_id: str) -> None:
    async with db.transaction() as conn:
        cursor = await conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        deleted = cursor.rowcount
        await cursor.close()
        if deleted == 0:
            raise KBNotFound(f"知识库不存在: {kb_id}")
        await conn.execute("DELETE FROM kb_chunks WHERE kb_id = ?", (kb_id,))
        await conn.execute("DELETE FROM kb_documents WHERE kb_id = ?", (kb_id,))
    knowledge_store.delete_kb(kb_id)


async def _refresh_counts(conn, kb_id: str) -> None:
    docs = await _count(conn, "SELECT COUNT(*) FROM kb_documents WHERE kb_id = ?", kb_id)
    chunks = await _count(conn, "SELECT COUNT(*) FROM kb_chunks WHERE kb_id = ?", kb_id)
    await conn.execute(
        "UPDATE knowledge_bases SET doc_count = ?, chunk_count = ? WHERE id = ?",
        (docs, chunks, kb_id),
    )


async def _count(conn, sql: str, kb_id: str) -> int:
    cursor = await conn.execute(sql, (kb_id,))
    try:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        await cursor.close()


async def add_document(kb_id: str, payload: KBDocumentCreate) -> KBDocument:
    kb = await get_kb(kb_id)
    now = utc_now()
    doc_id = f"doc_{now[:10].replace('-', '')}_{now[11:19].replace(':', '')}{_rand()}"
    title = payload.title.strip() or f"未命名文档 {now[:19]}"
    chunks = knowledge_rag.chunk_text(payload.content, kb.chunk_size, kb.overlap)
    if not chunks:
        raise ValueError("文档内容为空，无法切块")

    doc = KBDocument(
        id=doc_id,
        kb_id=kb_id,
        title=title,
        content=payload.content,
        chunk_count=len(chunks),
        created_at=now,
    )
    try:
        knowledge_store.save_document(doc)
    except OSError as exc:
        raise ValueError(f"文档落盘失败: {exc}") from exc

    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO kb_documents (id, kb_id, title, content, chunk_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, kb_id, title, payload.content, len(chunks), now),
        )
        await conn.executemany(
            "INSERT INTO kb_chunks (id, kb_id, doc_id, seq, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (f"{doc_id}_{index}", kb_id, doc_id, index, text, now)
                for index, text in enumerate(chunks)
            ],
        )
        await _refresh_counts(conn, kb_id)

    return doc


async def list_documents(kb_id: str) -> list[KBDocument]:
    await get_kb(kb_id)
    rows = await db.fetchall(
        "SELECT id, kb_id, title, content, chunk_count, created_at FROM kb_documents "
        "WHERE kb_id = ? ORDER BY created_at",
        (kb_id,),
    )
    docs = [
        KBDocument(
            id=row["id"],
            kb_id=row["kb_id"],
            title=row["title"],
            content=row["content"],
            chunk_count=row["chunk_count"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    # 老库第一次打开时把已有文档补成 md 源文件；SQLite 仍是检索索引。
    for doc in docs:
        try:
            knowledge_store.ensure_document(doc)
        except OSError:
            pass
    return docs


async def delete_document(kb_id: str, doc_id: str) -> None:
    async with db.transaction() as conn:
        # 先删子表再删主表：kb_chunks 通过 doc_id 外键引用 kb_documents，
        # 反过来删会撞 FOREIGN KEY 约束（本地是 PRAGMA foreign_keys=ON）
        await conn.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
        cursor = await conn.execute(
            "DELETE FROM kb_documents WHERE id = ? AND kb_id = ?", (doc_id, kb_id)
        )
        deleted = cursor.rowcount
        await cursor.close()
        if deleted == 0:
            raise KBDocumentNotFound(f"文档不存在: {doc_id}")
        await _refresh_counts(conn, kb_id)
    knowledge_store.delete_document(kb_id, doc_id)


async def search(kb_id: str, query: str, top_k: int = 4, rerank: bool = False) -> KBSearchResult:
    await get_kb(kb_id)
    rows = await db.fetchall(
        "SELECT c.doc_id, c.seq, c.text, d.title FROM kb_chunks c "
        "JOIN kb_documents d ON d.id = c.doc_id WHERE c.kb_id = ? ORDER BY c.doc_id, c.seq",
        (kb_id,),
    )
    chunks = [
        {"doc_id": row["doc_id"], "title": row["title"], "seq": row["seq"], "text": row["text"]}
        for row in rows
    ]
    hits, took_ms = knowledge_rag.search_chunks(query, chunks, top_k=top_k, rerank=rerank)

    hint = None
    if not chunks:
        hint = "这个知识库还没有文档，先在「知识库」页添加内容再检索"
    elif not hits:
        hint = "没有命中任何片段：换个更具体的查询词，或确认文档内容里确实有这些词"

    return KBSearchResult(
        kb_id=kb_id,
        query=query,
        hits=[KBHit(**hit) for hit in hits],
        total_chunks=len(chunks),
        took_ms=took_ms,
        hint=hint,
        extra={"rerank": rerank, "engine": "bm25+mmr" if rerank else "bm25"},
    )


def _rand() -> str:
    import uuid

    return uuid.uuid4().hex[:4]
