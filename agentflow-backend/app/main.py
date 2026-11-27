"""AgentFlow Studio API 入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import agents, artifacts, chat, flows, knowledge, mcp, nodes, resources, runs, settings as settings_api, tools, versions
from app.config import settings
from app.database import db, init_db
from app.services.run_manager import run_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # 先给执行器留下终态再关库，避免出现永远 running 的僵尸记录
    await run_manager.shutdown()
    await db.close()


app = FastAPI(title="AgentFlow Studio API", version="1.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(flows.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(mcp.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(versions.router, prefix="/api")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": "HTTP_ERROR", "message": str(exc.detail), "detail": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic v2 的 errors() 会在 ctx 里塞 ValueError 对象，直接 JSONResponse 会 500
    detail = []
    for error in exc.errors():
        item = dict(error)
        item.pop("url", None)
        if isinstance(item.get("ctx"), dict):
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        detail.append(item)
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "detail": detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}", "detail": None},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.1"}


# 生产构建产物可选托管；开发时用 Vite dev server + proxy。
_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="web")
