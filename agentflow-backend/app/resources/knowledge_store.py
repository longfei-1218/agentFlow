"""知识库文件存储：文档和 manifest 放用户资源目录，SQLite 继续做检索索引。

这不是「把知识库搬空」：SQLite 仍然是 chunk 检索的索引，文件目录是可读、可备份、
可迁移的源数据。外部导入/多人上传时，目录天然按 owner + kb_id 隔离。
"""
import json
from pathlib import Path

from app.config import settings
from app.models.knowledge import KBDocument, KnowledgeBase


def _root() -> Path:
    return Path(settings.RESOURCE_DATA_DIR).expanduser().resolve()


def _owner() -> str:
    return (settings.RESOURCE_OWNER_ID or "local").strip() or "local"


def kb_dir(kb_id: str) -> Path:
    return _root() / "users" / _owner() / "knowledge" / kb_id


def ensure_kb(kb: KnowledgeBase) -> Path:
    path = kb_dir(kb.id)
    (path / "documents").mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 1,
        "kind": "knowledge",
        "id": kb.id,
        "name": kb.name,
        "chunkSize": kb.chunk_size,
        "overlap": kb.overlap,
        "embeddingModel": kb.embedding_model,
        "storage": {"documents": "documents", "index": "sqlite"},
    }
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return path


def save_document(doc: KBDocument) -> Path:
    path = kb_dir(doc.kb_id) / "documents" / f"{doc.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    title = doc.title.replace("\r", " ").replace("\n", " ").strip()
    path.write_text(f"# {title}\n\n{doc.content}", encoding="utf-8")
    return path


def ensure_document(doc: KBDocument) -> Path:
    """老库第一次列出文档时补一份 md，源文件缺失才写，避免每次读取都覆盖。"""
    path = kb_dir(doc.kb_id) / "documents" / f"{doc.id}.md"
    if not path.is_file():
        return save_document(doc)
    return path


def delete_document(kb_id: str, doc_id: str) -> None:
    path = kb_dir(kb_id) / "documents" / f"{doc_id}.md"
    path.unlink(missing_ok=True)


def delete_kb(kb_id: str) -> None:
    import shutil

    shutil.rmtree(kb_dir(kb_id), ignore_errors=True)
