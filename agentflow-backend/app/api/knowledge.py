"""知识库 API（R5）：知识库 CRUD + 文档增删 + 检索测试。"""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from app.models.knowledge import (
    KBDocument,
    KBDocumentCreate,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KBSearchRequest,
    KBSearchResult,
)
from app.services import knowledge_repo

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeBase])
async def list_kbs():
    return await knowledge_repo.list_kbs()


@router.post("", response_model=KnowledgeBase, status_code=201)
async def create_kb(payload: KnowledgeBaseCreate):
    try:
        return await knowledge_repo.create_kb(payload)
    except knowledge_repo.KBNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "KB_NAME_CONFLICT", "message": str(exc), "detail": None},
        )


@router.get("/{kb_id}", response_model=KnowledgeBase)
async def get_kb(kb_id: str):
    try:
        return await knowledge_repo.get_kb(kb_id)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{kb_id}", response_model=KnowledgeBase)
async def update_kb(kb_id: str, payload: KnowledgeBaseCreate):
    try:
        return await knowledge_repo.update_kb(kb_id, payload)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except knowledge_repo.KBNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "KB_NAME_CONFLICT", "message": str(exc), "detail": None},
        )


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: str):
    try:
        await knowledge_repo.delete_kb(kb_id)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{kb_id}/documents", response_model=list[KBDocument])
async def list_documents(kb_id: str):
    try:
        return await knowledge_repo.list_documents(kb_id)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{kb_id}/documents", response_model=KBDocument, status_code=201)
async def add_document(kb_id: str, payload: KBDocumentCreate):
    try:
        return await knowledge_repo.add_document(kb_id, payload)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "KB_DOCUMENT_INVALID", "message": str(exc), "detail": None},
        )


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(kb_id: str, doc_id: str):
    try:
        await knowledge_repo.delete_document(kb_id, doc_id)
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except knowledge_repo.KBDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/{kb_id}/search", response_model=KBSearchResult)
async def search(kb_id: str, payload: KBSearchRequest):
    try:
        return await knowledge_repo.search(
            kb_id, payload.query, top_k=payload.top_k, rerank=payload.rerank
        )
    except knowledge_repo.KBNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
