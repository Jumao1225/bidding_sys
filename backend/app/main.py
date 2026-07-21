import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.schemas.response.common import error_response
from app.core.config import settings
from app.api.routers import api_router

from app.core.logger import setup_app_logging
from app.middleware.logging_middleware import LoggingMiddleware
from loguru import logger

from app.services.llm_service import llm_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_app_logging()
    logger.info("🚀 智能投标系统后端启动成功")
    
    # 预加载 Embedding 模型，使其一直常驻后台内存/显存
    try:
        logger.info("⏳ 正在后台预加载 Embedding 模型，请稍候...")
        llm_service._get_embeddings_model()
        logger.info("✅ Embedding 模型预加载完成，已常驻后台！")
    except Exception as e:
        logger.error(f"❌ Embedding 模型预加载失败: {e}")
        
    yield
    # Shutdown
    logger.info("🛑 系统安全关闭")

app = FastAPI(
    title="Bidding Sys API",
    description="智能投标辅助系统后台接口",
    version="1.0.0",
    lifespan=lifespan,
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled Exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=error_response(code=500, message="Internal Server Error: " + str(exc)).model_dump()
    )

# 注册日志拦截中间件
app.add_middleware(LoggingMiddleware)

# CORS 配置
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

# 挂载本地上传文件目录
import os
from fastapi.staticfiles import StaticFiles
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # backend dir
uploads_dir = os.path.join(base_dir, "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    # 直接运行此文件启动开发服务器
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
