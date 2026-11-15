"""FastAPI 应用入口。"""
from __future__ import annotations

import datetime as dt
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import ROOT_DIR, settings
from .database import init_db
from .llm import llm
from .routers import agent_api, chat, data, finance, knowledge

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    settings.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    description="面向学生、指导教师与竞赛管理人员的学科竞赛辅助服务智能体",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "app": settings.APP_NAME,
        "version": __version__,
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "llm": llm.status(),
    }


@app.get("/api/files/{filename}")
def download(filename: str):
    """导出文件下载。限定在 OUTPUT_DIR 内，防止路径穿越。"""
    safe = Path(filename).name
    path = (settings.OUTPUT_DIR / safe).resolve()
    if settings.OUTPUT_DIR.resolve() not in path.parents and path.parent != settings.OUTPUT_DIR.resolve():
        raise HTTPException(400, "非法路径")
    if not path.exists():
        raise HTTPException(404, "文件不存在或已过期")
    return FileResponse(path, filename=safe)


app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(data.router)
app.include_router(finance.router)
app.include_router(agent_api.router)


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception):  # noqa: ANN001
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务端错误：{type(exc).__name__}: {exc}"},
    )


FRONTEND = ROOT_DIR / "frontend"
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
