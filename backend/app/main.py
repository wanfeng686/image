from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.console import router as console_router

app = FastAPI(title="SmartSupport API", version="0.1.0")
app.include_router(auth_router)      # 运营台认证
app.include_router(chat_router)      # 顾客端聊天
app.include_router(console_router)   # 运营台（鉴权保护）
# API 路由先注册，优先级高于静态挂载


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "smart-support-backend"}


# 聊天 UI：单文件静态页挂在根路径（"/" 自动返回 index.html）
# 目录基于本文件位置计算，无论从哪个目录启动 uvicorn 都能找到
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
