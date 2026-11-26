"""工具注册表 API（R3）：CRUD + 试跑 + 调用记录。"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from app.models.tool import (
    BUILTIN_SCHEMAS,
    ToolCreate,
    ToolDef,
    ToolInvocation,
    ToolTestRequest,
)
from app.services import tool_repo, tool_runner
from app.services.event_bus import utc_now

router = APIRouter(prefix="/tools", tags=["tools"])

BUILTINS = [
    {"name": "echo", "description": "原样返回文本，用来验证参数传递链路"},
    {"name": "now", "description": "返回当前时间（ISO + 时间戳），无网络依赖"},
    {"name": "calc", "description": "安全四则运算（AST 白名单，不用 eval）"},
]


@router.get("", response_model=list[ToolDef])
async def list_tools(enabled: bool | None = Query(default=None)):
    return await tool_repo.list_tools(only_enabled=bool(enabled))


@router.get("/builtins")
async def list_builtins():
    """内置工具清单：新建工具时前端据此切换「内置」下拉，Schema 由后端给，前端不抄一份。"""
    return [
        {**item, "paramsSchema": BUILTIN_SCHEMAS[item["name"]]}
        for item in BUILTINS
    ]


@router.get("/invocations", response_model=list[ToolInvocation])
async def list_invocations(
    tool_id: str | None = Query(default=None, alias="toolId"),
    limit: int = Query(default=20, ge=1, le=100),
):
    return await tool_repo.list_invocations(tool_id=tool_id, limit=limit)


@router.post("", response_model=ToolDef, status_code=201)
async def create_tool(payload: ToolCreate):
    try:
        return await tool_repo.create_tool(payload)
    except tool_repo.ToolNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "TOOL_NAME_CONFLICT", "message": str(exc), "detail": None},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "TOOL_INVALID", "message": str(exc), "detail": None},
        )


@router.get("/{tool_id}", response_model=ToolDef)
async def get_tool(tool_id: str):
    try:
        return await tool_repo.get_tool(tool_id)
    except tool_repo.ToolNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{tool_id}", response_model=ToolDef)
async def update_tool(tool_id: str, payload: ToolCreate):
    try:
        return await tool_repo.update_tool(tool_id, payload)
    except tool_repo.ToolNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tool_repo.ToolNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "TOOL_NAME_CONFLICT", "message": str(exc), "detail": None},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "TOOL_INVALID", "message": str(exc), "detail": None},
        )


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(tool_id: str):
    try:
        await tool_repo.delete_tool(tool_id)
    except tool_repo.ToolNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/{tool_id}/test")
async def test_tool(tool_id: str, payload: ToolTestRequest):
    """试跑：和运行期共用同一套执行器，差别只有「不写 run_id / 不走幂等缓存」。

    失败返回 200 + ok:false，让前端能把 latency/attempts 一起展示出来，
    而不是只剩一句 422 —— 这两个数字才是判断「要不要去改超时/重试」的依据。
    """
    try:
        tool = await tool_repo.get_tool(tool_id)
    except tool_repo.ToolNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    started = utc_now()
    try:
        invocation = await tool_runner.invoke(
            tool, payload.args, skip_idempotency=not payload.use_idempotency
        )
        return {
            "ok": True,
            "status": invocation.status,
            "attempts": invocation.attempts,
            "latencyMs": invocation.latency_ms,
            "httpStatus": invocation.http_status,
            "result": invocation.result,
            "idemHit": invocation.idem_hit,
            "error": None,
            "startedAt": started,
        }
    except tool_runner.ToolError as exc:
        recent = await tool_repo.list_invocations(tool_id=tool.id, limit=1)
        last = recent[0] if recent else None
        return {
            "ok": False,
            "status": last.status if last else "error",
            "attempts": last.attempts if last else 0,
            "latencyMs": last.latency_ms if last else 0,
            "httpStatus": last.http_status if last else None,
            "result": None,
            "idemHit": False,
            "error": str(exc),
            "code": exc.code,
            "startedAt": started,
        }
