import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

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

def auto_migrate_db_constraints():
    """在服务启动时自动检查并迁移数据库唯一约束，确保支持多租户同名账号。"""
    try:
        from app.db.session import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            # 1. 检查并移除旧的单列 email 唯一索引
            conn.execute(text("DROP INDEX IF EXISTS ix_users_email;"))
            conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;"))
            # 2. 确保 email 普通索引存在（便于查询）
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);"))
            # 3. 确保复合唯一约束 uq_user_tenant_email 存在
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_tenant_email'
                    ) THEN
                        ALTER TABLE users ADD CONSTRAINT uq_user_tenant_email UNIQUE (tenant_id, email);
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("✅ 数据库多租户复合约束 (tenant_id, email) 自动同步/迁移成功！")
    except Exception as e:
        logger.warning(f"⚠️ 自动迁移数据库约束提示: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_app_logging()
    logger.info("🚀 智能投标系统后端启动成功 (全量模块已热重载 v3)")
    
    # 自动执行数据库多租户约束升级与同步
    auto_migrate_db_constraints()

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

# CORS 全量跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.BACKEND_CORS_ORIGINS else [str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
    allow_origin_regex=".*",
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
