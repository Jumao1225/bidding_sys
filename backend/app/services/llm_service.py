import json
import logging
from typing import Optional, Dict, Any, Type, TypeVar
from pydantic import BaseModel
from tenacity import retry, wait_exponential, stop_after_attempt

from app.core.config import settings
from app.services.audit_service import audit_service

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
        self._llm_cache = {}
        self.embeddings = None
        
        if self.is_configured:
            # 初始化默认 LLM，兼容旧代码
            self.raw_llm = self.get_llm(temperature=0.3, json_mode=False)
            self.llm = self.get_llm(temperature=0.3, json_mode=True)
            logger.info(f"LLM 引擎初始化成功: {settings.LLM_MODEL_NAME}")
        else:
            self.raw_llm = None
            self.llm = None
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

    def get_llm(self, temperature: float = 0.3, json_mode: bool = False):
        """
        根据指定的 temperature 和 json_mode 返回缓存的大模型实例。
        如果不存在，则动态创建一个并缓存。
        """
        if not self.is_configured:
            return None
            
        cache_key = f"{temperature}_{json_mode}"
        if cache_key not in self._llm_cache:
            try:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model_name=settings.LLM_MODEL_NAME,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_API_BASE if settings.OPENAI_API_BASE else None,
                    temperature=temperature,
                    request_timeout=60.0,  # 显式配置 60 秒请求超时，防止网络卡死
                )
                if json_mode:
                    llm = llm.bind(response_format={"type": "json_object"})
                self._llm_cache[cache_key] = llm
            except ImportError:
                logger.error("未找到 langchain-openai，请安装相关依赖。")
                return None
            except Exception as e:
                logger.error(f"创建 LLM 实例失败 (temp={temperature}, json={json_mode}): {str(e)}")
                return None
                
        return self._llm_cache[cache_key]

    def _get_embeddings_model(self):
        """懒加载 Embedding 模型，仅在首次使用时加载以缩短应用启动时间"""
        if self.embeddings is None:
            import os
            # 解决 Windows 环境下 Celery / PyTorch 加载时的 OpenMP 冲突崩溃问题
            os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            import torch  # 引入 torch 用以精确控制精度
            from langchain_huggingface import HuggingFaceEmbeddings
            
            if hasattr(self, 'local_model_path') and os.path.exists(self.local_model_path):
                logger.info(f"正在加载本地 Embedding 模型 (首次使用懒加载): {self.local_model_path}")
                
                # 1. 核心修复：显式强制使用 float32 全精度，防止 fp16 导致 NaN 溢出
                model_kwargs = {
                    'device': 'cuda' if torch.cuda.is_available() else 'cpu', # 自动选择 GPU 或 CPU
                    'model_kwargs': {'torch_dtype': torch.float32}  # 正确将 torch_dtype 传递给底层 Transformer 模型
                }
                
                # 2. 优化推理：控制 batch_size 和 归一化 (减小 batch_size 防止 CPU 内存溢出)
                encode_kwargs = {
                    'normalize_embeddings': True,  # BGE 模型推荐开启归一化（使检索时余弦相似度计算更准确）
                    'batch_size': 4
                }
                
                # 3. 实例化模型并限制最大序列长度 (8192)
                self.embeddings = HuggingFaceEmbeddings(
                    model_name=self.local_model_path,
                    model_kwargs=model_kwargs,
                    encode_kwargs=encode_kwargs
                )
                # 防御性配置：显式指定 Hugging Face SentenceTransformer 客户端的最大截断上下文长度
                if hasattr(self.embeddings, 'client') and hasattr(self.embeddings.client, 'max_seq_length'):
                    self.embeddings.client.max_seq_length = 8192

                logger.info("✅ 本地 Embedding 模型加载成功 (单例已刷新)，已启用全精度(float32)与8192上下文截断防护。")
            else:
                raise ValueError(f"❌ 无法生成向量：本地 Embedding 模型目录不存在，当前配置路径: {getattr(self, 'local_model_path', '未定义')}")
                
        return self.embeddings

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def generate_structured_json(self, prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
        """
        发送 Prompt 并期望返回 JSON 格式的结构化数据。
        支持传入自定义温度 (默认 0.3)。
        如果未配置 API Key，直接抛出异常，不再提供 Mock 数据兜底。
        """
        if not self.is_configured:
            raise ValueError("❌ 无法进行大模型解析：尚未配置有效的 OPENAI_API_KEY")
            
        llm = self.get_llm(temperature=temperature, json_mode=True)
        if llm is None:
            raise ValueError("❌ 无法获取 LLM 实例")
            
        try:
            import time
            import re
            start_time = time.time()
            response = llm.invoke(prompt)
            end_time = time.time()
            content = response.content
            
            # 提取 Token 消耗
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
                token_usage = response.response_metadata['token_usage']
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)
                
            audit_service.log_event(
                action_type="llm_call",
                inputs={"prompt": prompt},
                outputs={"content": content},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=int((end_time - start_time) * 1000)
            )
            
            # 强化型 Markdown 代码块与前导/后置文本清洗
            clean_content = content.strip()
            # 1. 尝试使用正则匹配 ```json ... ``` 块
            json_code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
            if json_code_block_match:
                clean_content = json_code_block_match.group(1).strip()
            else:
                # 2. 兜底提取最外层的 { ... } 或 [ ... ]
                json_obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", clean_content)
                if json_obj_match:
                    clean_content = json_obj_match.group(1).strip()
            
            # 解析 JSON
            return json.loads(clean_content)
        except json.JSONDecodeError as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=f"JSONDecodeError: {str(e)}")
            logger.error(f"❌ 大模型返回内容解析 JSON 失败: {str(e)}, 原始返回片段: {content[:300] if 'content' in locals() else 'None'}")
            raise ValueError(f"大模型返回内容解析 JSON 失败: {str(e)}")
        except Exception as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=str(e))
            logger.error(f"❌ LLM 调用过程发生异常: {str(e)}")
            raise e

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def generate_text(self, prompt: str, temperature: float = 0.3) -> str:
        """
        发送 Prompt 并返回纯文本生成结果。
        """
        if not self.is_configured:
            raise ValueError("❌ 无法进行大模型解析：尚未配置有效的 OPENAI_API_KEY")

        llm = self.get_llm(temperature=temperature, json_mode=False)
        if llm is None:
            raise ValueError("❌ 无法获取 LLM 实例")

        try:
            import time
            start_time = time.time()
            response = llm.invoke(prompt)
            end_time = time.time()
            content = str(response.content) if hasattr(response, 'content') else str(response)

            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
                token_usage = response.response_metadata['token_usage']
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)

            audit_service.log_event(
                action_type="llm_call_text",
                inputs={"prompt": prompt},
                outputs={"content": content},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=int((end_time - start_time) * 1000)
            )

            return content.strip()
        except Exception as e:
            audit_service.log_event(action_type="llm_call_text", status="error", error_message=str(e))
            logger.error(f"❌ LLM 文本生成过程发生异常: {str(e)}")
            raise e


    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def generate_structured_output(self, prompt: str, schema_cls: Type[BaseModel], temperature: float = 0.1) -> BaseModel:
        """
        利用大模型原生的 Structured Outputs 能力直接生成校验过的 Pydantic 对象。
        如果当前模型(如某些兼容 API)不支持，则平滑降级到 json_mode 并手动反序列化，
        并具备智能外层包装节点 (Root Key Unwrap) 解包能力。
        """
        if not self.is_configured:
            raise ValueError("❌ 无法进行大模型解析：尚未配置有效的 OPENAI_API_KEY")
            
        import time
        
        # 1. 尝试首选策略: Native Structured Outputs
        # 注意: DeepSeek API 目前不支持 response_format="json_schema"，强行调用会报 400 错误。
        # 因此，如果是 DeepSeek 模型，我们直接跳过原生调用，节省一次网络开销。
        is_deepseek = "deepseek" in settings.LLM_MODEL_NAME.lower() or (settings.OPENAI_API_BASE and "deepseek" in settings.OPENAI_API_BASE.lower())
        
        if not is_deepseek:
            llm_raw = self.get_llm(temperature=temperature, json_mode=False)
            try:
                structured_llm = llm_raw.with_structured_output(schema_cls)
                start_time = time.time()
                response = structured_llm.invoke(prompt)
                end_time = time.time()
                
                audit_service.log_event(
                    action_type="llm_call_structured",
                    inputs={"prompt": prompt, "schema": schema_cls.__name__},
                    outputs={"content": "Structured output successful"},
                    execution_time_ms=int((end_time - start_time) * 1000)
                )
                return response
                
            except Exception as e:
                logger.warning(f"Native Structured Output 失败 ({str(e)})，自动降级到 JSON Mode...")
        
        # 2. 兜底策略 (DeepSeek 默认走此路线): JSON Mode + Schema 注入
        schema_dict = schema_cls.model_json_schema() if hasattr(schema_cls, "model_json_schema") else schema_cls.schema()
        schema_json = json.dumps(schema_dict, indent=2, ensure_ascii=False)
            
        fallback_prompt = f"{prompt}\n\n【强制格式约束】\n必须返回严格符合以下 JSON Schema 的纯 JSON 格式：\n{schema_json}\n\n[极其重要]\n1. 只能输出纯 JSON 数据，绝对不要用 ```json 标签包裹！\n2. 确保所有的双引号、括号、逗号等符号完美匹配，不允许出现任何语法错误。"
        
        extracted_dict = self.generate_structured_json(fallback_prompt, temperature=temperature)
        
        # 3. 智能根节点解包 (Auto-Unwrap Root Key) 机制
        if isinstance(extracted_dict, dict):
            expected_fields = set(schema_cls.model_fields.keys()) if hasattr(schema_cls, "model_fields") else set(schema_cls.__fields__.keys())
            # 如果当前字典的顶层不包含 Schema 期望的字段，检查是否被大模型在最外层包装了一层 root key
            if not any(field in extracted_dict for field in expected_fields):
                # 检查常见的大模型包装 Key
                candidates = [schema_cls.__name__, schema_cls.__name__.lower(), "data", "result", "output", "properties", "response"]
                unwrapped = False
                for cand in candidates:
                    if cand in extracted_dict and isinstance(extracted_dict[cand], dict):
                        logger.info(f"💡 检测到大模型外层包装 Key '{cand}'，正在自动解包...")
                        extracted_dict = extracted_dict[cand]
                        unwrapped = True
                        break
                # 如果没有匹配到常用名称，但顶层只有唯一的 1 个 Key 且值也是字典，自动解包该 Key
                if not unwrapped and len(extracted_dict) == 1:
                    single_val = list(extracted_dict.values())[0]
                    if isinstance(single_val, dict):
                        single_key = list(extracted_dict.keys())[0]
                        logger.info(f"💡 自动解包唯一外层 Key '{single_key}'...")
                        extracted_dict = single_val

        # 4. 反序列化校验
        try:
            if hasattr(schema_cls, "model_validate"):
                return schema_cls.model_validate(extracted_dict)
            else:
                return schema_cls.parse_obj(extracted_dict)
        except Exception as val_err:
            logger.error(f"❌ Pydantic Schema ({schema_cls.__name__}) 反序列化校验失败: {val_err}. 字典内容片段: {str(extracted_dict)[:300]}")
            raise ValueError(f"大模型提取格式不匹配 Schema ({schema_cls.__name__}): {val_err}") from val_err

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def expand_query(self, query: str, num_variants: int = 3, temperature: float = 0.7) -> list[str]:
        """
        多路查询重写 (Query Expansion)。
        利用 LLM 将单一关键词扩展为多个相关的语义变体。
        使用较高的 temperature (默认 0.7) 来增加发散性。
        """
        if not self.is_configured:
            return [query]
            
        llm = self.get_llm(temperature=temperature, json_mode=True)
        if llm is None:
            return [query]
            
        prompt = f"""
        你是一个工程招投标领域的搜索专家。
        用户的原始搜索词是："{query}"
        
        为了在向量数据库中尽可能多地召回相关的上下文（避免遗漏隐晦表达或同义词），
        请给出 {num_variants} 个不同的搜索词变体。
        变体应该包含原词的同义词、具体场景词或技术术语。
        
        【输出格式要求】
        严格输出一个 JSON 格式，必须包含 "variants" 键，其值为字符串数组。例如：
        {{"variants": ["变体1", "变体2", "变体3"]}}
        不要输出任何其他解释。
        """
        try:
            import time
            start_time = time.time()
            # 调用具有较高发散性的 LLM 实例
            response = llm.invoke(prompt)
            end_time = time.time()
            content = response.content
            
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
                token_usage = response.response_metadata['token_usage']
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)
                
            audit_service.log_event(
                action_type="llm_call",
                inputs={"prompt": prompt},
                outputs={"content": content},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=int((end_time - start_time) * 1000)
            )
            
            import json
            result = json.loads(content)
            
            variants = result.get("variants", [])
            if isinstance(variants, list):
                # 合并原查询词和变体
                expanded = [query] + [str(v) for v in variants]
                # 去重并保留顺序，去除空字符串
                expanded = list(dict.fromkeys([v.strip() for v in expanded if v.strip()]))
                return expanded
            return [query]
        except Exception as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=str(e))
            logger.warning(f"查询扩展失败，回退到原始查询: {str(e)}")
            return [query]

    async def astream_chat(self, messages: list, temperature: float = 0.7):
        """
        异步流式聊天接口，专为 ChatPanel 打字机效果设计。
        基于 LangChain astream() 逐 token 推送，DeepSeek 模型完全兼容。

        Args:
            messages: LangChain 消息格式列表，如 [SystemMessage(...), HumanMessage(...)]
            temperature: 生成温度，聊天场景建议 0.7

        Yields:
            str: 每次推送的 token 片段
        """
        if not self.is_configured:
            raise ValueError("❌ 无法进行大模型调用：尚未配置有效的 OPENAI_API_KEY")

        # 聊天场景不需要 json_mode，使用普通 raw LLM 实例
        llm = self.get_llm(temperature=temperature, json_mode=False)
        if llm is None:
            raise ValueError("❌ 无法获取 LLM 实例")

        logger.info(f"开始异步流式聊天，消息轮数: {len(messages)}，温度: {temperature}")
        try:
            async for chunk in llm.astream(messages):
                # LangChain 返回的 chunk 是 AIMessageChunk 对象，content 为 token 片段
                if hasattr(chunk, "content") and chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error(f"流式聊天异常: {str(e)}")
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
