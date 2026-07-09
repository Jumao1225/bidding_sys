from pydantic_settings import BaseSettings
from typing import List, Union
import os
from dotenv import load_dotenv

# 手动加载 .env 文件，确保 os.getenv 能在类定义时读到值
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), ".env"))
class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    
    # 必须连接 PostgreSQL，不再退化回 SQLite
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL")
    
    # 数据库连接池配置
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", 20))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", 10))
    
    # 鉴权机制：在实例化 Settings 时检查
    def __init__(self, **data):
        super().__init__(**data)
        if not self.SQLALCHEMY_DATABASE_URI or not self.SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
            raise ValueError("❌ 启动失败：未正确配置 PostgreSQL 数据库地址 (DATABASE_URL)。为了保证数据安全，系统拒绝退化回 SQLite！")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173", 
        "http://localhost:3000", 
        "http://localhost:5174",
        "http://127.0.0.1:5174"
    ]
    
    # OpenAI/LLM 配置预留
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gpt-4o")

    class Config:
        env_file = ("../.env", ".env")
        case_sensitive = True
        extra = "ignore"

settings = Settings()
