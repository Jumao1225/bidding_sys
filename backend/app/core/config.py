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
    
    # JWT Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173", 
        "http://localhost:3000", 
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174"
    ]
    
    # OpenAI/LLM 配置预留
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gpt-4o")

    # 所有 LLM 模型共用的输出上限；调用层传入 max_output_tokens 时可单独覆盖。
    LLM_MAX_OUTPUT_TOKENS: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "100000"))
    # LLM 单次 HTTP 请求最长等待时间，默认 15 分钟，适配长上下文模型生成场景。
    LLM_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "900"))
    # BOM 等结构化提取默认关闭思考模式，避免 reasoning token 挤占 JSON 输出空间。
    DEEPSEEK_THINKING_ENABLED: bool = os.getenv("DEEPSEEK_THINKING_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    # GLM 聊天场景默认保留模型思考能力；结构化 JSON 调用由服务层单独关闭思考，保护 JSON 输出预算。
    GLM_THINKING_ENABLED: bool = os.getenv("GLM_THINKING_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    # 切换或继续 GLM 会话时默认清理历史思考字段，避免跨轮次携带不完整的 reasoning_content。
    GLM_CLEAR_THINKING: bool = os.getenv("GLM_CLEAR_THINKING", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    # ChatAgent 国内模型应用侧上下文压缩配置，不依赖 provider 的原生 compaction 能力。
    CHAT_CONTEXT_SUMMARY_TRIGGER_TOKENS: int = int(
        os.getenv("CHAT_CONTEXT_SUMMARY_TRIGGER_TOKENS", "12000")
    )
    CHAT_CONTEXT_KEEP_RECENT_MESSAGES: int = int(
        os.getenv("CHAT_CONTEXT_KEEP_RECENT_MESSAGES", "8")
    )

    # ChatAgent 主链路的网络重试配置；采用有上限的重试，避免请求永久占用连接和重复执行工具。
    CHAT_LLM_MAX_RETRIES: int = int(os.getenv("CHAT_LLM_MAX_RETRIES", "5"))
    CHAT_LLM_RETRY_BACKOFF_SECONDS: float = float(
        os.getenv("CHAT_LLM_RETRY_BACKOFF_SECONDS", "2")
    )
    CHAT_LLM_RETRY_BACKOFF_MAX_SECONDS: float = float(
        os.getenv("CHAT_LLM_RETRY_BACKOFF_MAX_SECONDS", "30")
    )

    # ======= VLM 双引擎配置 =======
    VLM_PROVIDER: str = os.getenv("VLM_PROVIDER", "ali")
    
    # 1. 阿里通义千问配置
    ALI_VLM_API_BASE: str = os.getenv("ALI_VLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    ALI_VLM_API_KEY: str = os.getenv("ALI_VLM_API_KEY", "")
    ALI_VLM_MODEL_NAME: str = os.getenv("ALI_VLM_MODEL_NAME", "qwen-vl-plus")
    
    # 2. 本地部署配置
    LOCAL_VLM_API_BASE: str = os.getenv("LOCAL_VLM_API_BASE", "http://221.224.69.13:8083/v1")
    LOCAL_VLM_API_KEY: str = os.getenv("LOCAL_VLM_API_KEY", "")
    LOCAL_VLM_MODEL_NAME: str = os.getenv("LOCAL_VLM_MODEL_NAME", "minimax-m3-mxfp8")
    # ===============================

    # MinerU 在线 API 配置 (参考 https://mineru.net/apiManage/docs)
    MINERU_API_TOKEN: str = os.getenv("MINERU_API_TOKEN", "")
    MINERU_API_BASE_URL: str = os.getenv("MINERU_API_BASE_URL", "https://mineru.net/api/v4")

    # Multi-Agent 标书起草长流程开关 (false: 开启; true: 跳过)
    SKIP_BID_FILLER: bool = os.getenv("SKIP_BID_FILLER", "false").lower() in ("true", "1", "yes")
    # 标书撰写由独立子进程执行，默认允许两份不同标书并行，仍由文档锁阻止同文档重复写入。
    BID_FILL_MAX_CONCURRENCY: int = int(os.getenv("BID_FILL_MAX_CONCURRENCY",10))
    BID_FILL_LOCK_TTL_SECONDS: int = int(os.getenv("BID_FILL_LOCK_TTL_SECONDS", 14400))


    class Config:
        env_file = ("../.env", ".env")
        case_sensitive = True
        extra = "ignore"

settings = Settings()
