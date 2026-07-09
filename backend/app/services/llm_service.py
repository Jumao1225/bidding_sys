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

# 暴露单例实例供外部模块直接引用
llm_service = LLMService()
