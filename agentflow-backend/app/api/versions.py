"""版本管理统一入口：列表页所需的资源版本状态，以及按 kind 取版本详情。"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.models.version import ResourceVersionState, VersionDetail
from app.services import version_repo

router = APIRouter(prefix="/versions", tags=["versions"])

_KINDS = {"agent", "flow"}


@router.get("", response_model=list[ResourceVersionState])
async def list_resources():
    return await version_repo.list_resource_states()


@router.get("/{kind}/{resource_id}/{version}", response_model=VersionDetail)
async def get_version(kind: str, resource_id: str, version: int):
    if kind not in _KINDS:
        return JSONResponse(
            status_code=400,
            content={"code": "VERSION_KIND_INVALID", "message": f"未知版本类型: {kind}", "detail": None},
        )
    try:
        return await version_repo.get_version(kind, resource_id, version)
    except version_repo.VersionNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"code": "VERSION_NOT_FOUND", "message": str(exc), "detail": None},
        )
