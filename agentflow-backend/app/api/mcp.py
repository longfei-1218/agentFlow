"""MCP Server API（R5）：注册表 CRUD + 探测工具 + 试跑调用。"""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from app.models.mcp import (
    MCPCallRequest,
    MCPCallResult,
    MCPProbeResult,
    MCPServerCreate,
    MCPServerDef,
)
from app.services import mcp_client, mcp_repo

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])


@router.get("", response_model=list[MCPServerDef])
async def list_servers():
    return await mcp_repo.list_servers()


@router.post("", response_model=MCPServerDef, status_code=201)
async def create_server(payload: MCPServerCreate):
    try:
        return await mcp_repo.create_server(payload)
    except mcp_repo.MCPNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "MCP_NAME_CONFLICT", "message": str(exc), "detail": None},
        )


@router.get("/{server_id}", response_model=MCPServerDef)
async def get_server(server_id: str):
    try:
        return await mcp_repo.get_server(server_id)
    except mcp_repo.MCPServerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{server_id}", response_model=MCPServerDef)
async def update_server(server_id: str, payload: MCPServerCreate):
    try:
        return await mcp_repo.update_server(server_id, payload)
    except mcp_repo.MCPServerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mcp_repo.MCPNameConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "MCP_NAME_CONFLICT", "message": str(exc), "detail": None},
        )


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: str):
    try:
        await mcp_repo.delete_server(server_id)
    except mcp_repo.MCPServerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{server_id}/tools", response_model=MCPProbeResult)
async def probe_server(server_id: str):
    """探测工具清单。失败也返回 200 + ok:false：探测本来就是排错动作，
    把超时/退出/stderr 一起给出来，比一个 502 有用。"""
    try:
        server = await mcp_repo.get_server(server_id)
    except mcp_repo.MCPServerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        tools, latency = await mcp_client.probe_tools(server)
        return MCPProbeResult(ok=True, tools=tools, latency_ms=latency)
    except mcp_client.MCPError as exc:
        return MCPProbeResult(ok=False, error=str(exc), code=exc.code)


@router.post("/{server_id}/call", response_model=MCPCallResult)
async def call_server_tool(server_id: str, payload: MCPCallRequest):
    try:
        server = await mcp_repo.get_server(server_id)
    except mcp_repo.MCPServerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        text, raw, latency = await mcp_client.call_tool(server, payload.tool_name, payload.args)
        return MCPCallResult(ok=True, result=text, raw=raw, latency_ms=latency)
    except mcp_client.MCPError as exc:
        return MCPCallResult(ok=False, error=str(exc), code=exc.code)
