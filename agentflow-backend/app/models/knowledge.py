"""知识库契约（R5）。

检索走本地 BM25（中文按字符 bigram 切），不依赖 embedding 服务：
- 本地单用户原型里，「配一个 embedding key 才能用知识库」是不必要的门槛；
- 检索结果可复现、零成本，评测回归才稳定；
- 真要接向量库时，`embedding_model` 字段留着，chunk 表结构不用动。
"""
from typing import Any

from pydantic import Field

from app.models.flow import CamelModel


class KnowledgeBase(CamelModel):
    id: str
    name: str
    collection: str = ""
    chunk_size: int = Field(default=400, ge=50, le=2000)
    overlap: int = Field(default=50, ge=0, le=500)
    embedding_model: str = "bm25-local"
    doc_count: int = 0
    chunk_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class KnowledgeBaseCreate(CamelModel):
    name: str = Field(min_length=1, max_length=64)
    chunk_size: int = Field(default=400, ge=50, le=2000)
    overlap: int = Field(default=50, ge=0, le=500)
    embedding_model: str = "bm25-local"


class KBDocument(CamelModel):
    id: str
    kb_id: str
    title: str
    content: str
    chunk_count: int = 0
    created_at: str | None = None


class KBDocumentCreate(CamelModel):
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=1)


class KBHit(CamelModel):
    doc_id: str
    title: str
    seq: int
    text: str
    score: float


class KBSearchRequest(CamelModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)
    rerank: bool = False


class KBSearchResult(CamelModel):
    kb_id: str
    query: str
    hits: list[KBHit] = Field(default_factory=list)
    total_chunks: int = 0
    took_ms: int = 0
    # 没命中时给一句人话：空知识库 / 查询词太泛，前端直接显示
    hint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
