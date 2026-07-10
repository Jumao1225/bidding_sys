import json
import logging
from typing import Optional, Dict, Any
from tenacity import retry, wait_exponential, stop_after_attempt

from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMService:
    """
    统一的大语言模型 (LLM) 服务模块。
    封装了 LangChain 调用，实现与底层具体模型的解耦。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.is_configured = bool(settings.OPENAI_API_KEY)
        self.llm = None
        self.embeddings = None
        
        if self.is_configured:
            try:
                from langchain_openai import ChatOpenAI
                
                # 初始化 LangChain 的 ChatOpenAI 客户端
                # bind(response_format={"type": "json_object"}) 强制 OpenAI 模型返回 JSON
                self.llm = ChatOpenAI(
                    model_name=settings.LLM_MODEL_NAME,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_API_BASE if settings.OPENAI_API_BASE else None,
                    temperature=0.3,
                ).bind(response_format={"type": "json_object"})
                
                logger.info(f"LLM 引擎初始化成功: {settings.LLM_MODEL_NAME}")
            except ImportError:
                logger.error("未找到 langchain-openai，请安装相关依赖。")
                self.is_configured = False
            except Exception as e:
                logger.error(f"LLM 初始化失败: {str(e)}")
                self.is_configured = False
        else:
            logger.warning("未配置 OPENAI_API_KEY。")

        # 记录 Embedding 模型路径，但不立即加载（实现懒加载）
        self.embeddings = None
        try:
            import os
            
            # 计算项目根目录并查找 models/bge-m3
            bidding_sys_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            models_dir = os.path.join(bidding_sys_dir, "models")
            self.local_model_path = os.path.join(models_dir, "bge-m3")
            
            if not os.path.exists(self.local_model_path):
                logger.warning(f"⚠️ 本地模型目录不存在: {self.local_model_path}，请先运行 download_model.py 脚本下载模型。")
        except Exception as e:
            logger.error(f"Embedding 初始化异常: {str(e)}")

    def _get_embeddings_model(self):
        """懒加载 Embedding 模型，仅在首次使用时加载以缩短应用启动时间"""
        if self.embeddings is None:
            import os
            from langchain_huggingface import HuggingFaceEmbeddings
            if hasattr(self, 'local_model_path') and os.path.exists(self.local_model_path):
                logger.info(f"正在加载本地 Embedding 模型 (首次使用懒加载): {self.local_model_path}")
                self.embeddings = HuggingFaceEmbeddings(model_name=self.local_model_path)
            else:
                raise ValueError("❌ 无法生成向量：本地 Embedding 模型目录不存在，请先下载。")
        return self.embeddings

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def generate_structured_json(self, prompt: str) -> Dict[str, Any]:
        """
        发送 Prompt 并期望返回 JSON 格式的结构化数据。
        如果未配置 API Key，直接抛出异常，不再提供 Mock 数据兜底。
        """
        if not self.is_configured or self.llm is None:
            raise ValueError("❌ 无法进行大模型解析：尚未配置有效的 OPENAI_API_KEY")
            
        try:
            # LangChain 调用
            response = self.llm.invoke(prompt)
            content = response.content
            
            # 解析 JSON
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"大模型返回的不是合法 JSON: {str(e)}")
            raise ValueError(f"大模型返回内容解析 JSON 失败: {str(e)}")
        except Exception as e:
            logger.error(f"LLM 调用失败: {str(e)}")
            raise e

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        为给定的文本列表生成嵌入向量 (Embeddings)。
        返回 1024 维的 BGE-M3 向量列表。
        """
        try:
            embeddings_model = self._get_embeddings_model()
            return embeddings_model.embed_documents(texts)
        except Exception as e:
            logger.error(f"Embedding 生成失败: {str(e)}")
            raise e

# 暴露单例实例供外部模块直接引用
llm_service = LLMService()
