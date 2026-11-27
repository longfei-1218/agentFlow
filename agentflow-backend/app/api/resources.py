"""资源包导入 API：本地 MCP zip、远程 MCP manifest、HTTP 工具 manifest。"""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.resource import ResourceImportResult
from app.services import resource_importer

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("")
async def list_resources():
    return await resource_importer.overview()


@router.post("/import", response_model=ResourceImportResult)
async def import_resource(
    kind: str = Form(...),
    file: UploadFile | None = File(default=None),
    manifest: str | None = Form(default=None),
):
    """导入并验证资源。

    - kind=mcp_local：file 必填，zip 里必须有 manifest.json；
    - kind=mcp_remote：manifest 必填，JSON 里 transport=http + url；
    - kind=http_tool：manifest 必填，JSON 声明 method/url/paramsSchema。
    """
    if kind == "mcp_local":
        if file is None:
            raise HTTPException(status_code=400, detail="mcp_local 必须上传 zip 文件")
        data = await file.read()
        return await resource_importer.import_mcp_zip(data)

    raw = manifest
    if file is not None and not (raw or "").strip():
        raw = (await file.read()).decode("utf-8", errors="replace")

    if not (raw or "").strip():
        raise HTTPException(status_code=400, detail=f"{kind} 必须提供 manifest JSON")

    if kind == "mcp_remote":
        return await resource_importer.import_mcp_remote(raw)
    if kind == "http_tool":
        return await resource_importer.import_http_tool(raw)
    raise HTTPException(status_code=400, detail=f"不支持的导入类型: {kind}")
