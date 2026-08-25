import json
import hashlib
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
        self._global_is_configured = bool(settings.OPENAI_API_KEY)
        self._llm_cache = {}
        self.embeddings = None
        
        if self._global_is_configured:
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

    def reload_runtime_config(self) -> None:
        """清理 LLM 缓存并按最新运行时配置重建实例。"""
        self._llm_cache.clear()
        self._global_is_configured = bool(settings.OPENAI_API_KEY)
        if not self._global_is_configured:
            self._raw_llm = None
            self._llm = None
            logger.warning("模型配置热更新后未配置 OPENAI_API_KEY，LLM 暂不可用。")
            return

        self.raw_llm = self.get_llm(temperature=0.3, json_mode=False)
        self.llm = self.get_llm(temperature=0.3, json_mode=True)
        logger.info("LLM 配置已热更新: %s", settings.LLM_MODEL_NAME)

    @property
    def is_configured(self) -> bool:
        """按当前请求租户判断 LLM 是否配置完成。"""
        return bool(self._get_runtime_values().get("OPENAI_API_KEY"))

    @property
    def raw_llm(self):
        """返回当前请求租户的普通 LLM，兼容已有 Agent 调用方式。"""
        from app.core.context import current_tenant_id
        if current_tenant_id.get():
            return self.get_llm(temperature=0.3, json_mode=False)
        return self._raw_llm

    @raw_llm.setter
    def raw_llm(self, value):
        self._raw_llm = value

    @property
    def llm(self):
        """返回当前请求租户的 JSON LLM。"""
        from app.core.context import current_tenant_id
        if current_tenant_id.get():
            return self.get_llm(temperature=0.3, json_mode=True)
        return self._llm

    @llm.setter
    def llm(self, value):
        self._llm = value

    def invalidate_tenant_cache(self, tenant_id: str) -> None:
        """清除单个租户的 LLM 客户端缓存。"""
        prefix = f"{tenant_id}:"
        self._llm_cache = {
            key: value for key, value in self._llm_cache.items() if not key.startswith(prefix)
        }

    def _get_runtime_values(self) -> Dict[str, str]:
        """读取当前请求租户的有效模型配置。"""
        from app.core.context import current_tenant_id
        from app.services.model_config_service import model_config_service

        return model_config_service.get_values(current_tenant_id.get())

    def get_llm(self, temperature: float = 0.3, json_mode: bool = False):
        """
        根据指定的 temperature 和 json_mode 返回缓存的大模型实例。
        如果不存在，则动态创建一个并缓存。
        """
        runtime_values = self._get_runtime_values()
        if not runtime_values.get("OPENAI_API_KEY"):
            return None
            
        from app.core.context import current_tenant_id
        tenant_id = current_tenant_id.get() or "global"
        config_fingerprint = hashlib.sha256(
            f"{runtime_values['OPENAI_API_KEY']}\0{runtime_values['OPENAI_API_BASE']}\0{runtime_values['LLM_MODEL_NAME']}".encode()
        ).hexdigest()[:16]
        cache_key = f"{tenant_id}:{config_fingerprint}:{temperature}_{json_mode}"
        if cache_key not in self._llm_cache:
            try:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model_name=runtime_values["LLM_MODEL_NAME"],
                    api_key=runtime_values["OPENAI_API_KEY"],
                    base_url=runtime_values["OPENAI_API_BASE"] if runtime_values["OPENAI_API_BASE"] else None,
                    temperature=temperature,
                    request_timeout=300.0,  # 显式配置请求超时，防止网络卡死
                    max_retries=3,  # 显式配置底层 HTTP 瞬时网络错误自动重试
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

            exec_time_ms = int((end_time - start_time) * 1000)
            logger.info(
                f"🤖 [LLM 调用完成] ({settings.LLM_MODEL_NAME}) | 耗时: {exec_time_ms}ms | "
                f"Prompt: {prompt_tokens:,} | Completion: {completion_tokens:,} | Total: {prompt_tokens + completion_tokens:,}"
            )
                
            audit_service.log_event(
                action_type="llm_call",
                inputs={"prompt": prompt},
                outputs={"content": content},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=exec_time_ms
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
            
            # 解析 JSON (支持 strict=False 与控制字符自动清洗自愈)
            try:
                return json.loads(clean_content, strict=False)
            except json.JSONDecodeError:
                # 二级自愈：清洗不可见控制字符 (保留标准换行) 并将裸换行转义
                repaired_content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_content)
                try:
                    return json.loads(repaired_content, strict=False)
                except Exception:
                    # 三级自愈：使用内置简易清洗器
                    pass
                raise
        except json.JSONDecodeError as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=f"JSONDecodeError: {str(e)}")
            logger.error(f"❌ 大模型返回内容解析 JSON 失败: {str(e)}, 原始返回片段: {content[:300] if 'content' in locals() else 'None'}")
            raise ValueError(f"大模型返回内容解析 JSON 失败: {str(e)}")
        except Exception as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=str(e))
            logger.error(f"❌ LLM 调用过程发生异常: {str(e)}")
            raise e

    # 兼容便捷别名
    generate_json = generate_structured_json

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

            exec_time_ms = int((end_time - start_time) * 1000)
            logger.info(
                f"🤖 [LLM 文本生成完成] ({settings.LLM_MODEL_NAME}) | 耗时: {exec_time_ms}ms | "
                f"Prompt: {prompt_tokens:,} | Completion: {completion_tokens:,} | Total: {prompt_tokens + completion_tokens:,}"
            )

            audit_service.log_event(
                action_type="llm_call_text",
                inputs={"prompt": prompt},
                outputs={"content": content},
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=exec_time_ms
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
        runtime_values = self._get_runtime_values()
        is_deepseek = "deepseek" in runtime_values["LLM_MODEL_NAME"].lower() or (
            runtime_values["OPENAI_API_BASE"] and "deepseek" in runtime_values["OPENAI_API_BASE"].lower()
        )
        
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
            
        fallback_prompt = (
            f"{prompt}\n\n"
            f"【强制格式约束】\n"
            f"请从原文中提取真实的业务数据，返回一个填入了具体提取结果的 JSON 数据对象 (Data Instance)，"
            f"必须严格符合以下 JSON Schema 结构定义：\n{schema_json}\n\n"
            f"【极其重要 - 严格禁止事项】\n"
            f"1. 你必须返回填写了真实提取数据的 JSON 对象，绝对禁止直接复制或返回 JSON Schema 的定义字典本身！（严禁在 JSON 键值中包含 'title', 'description', 'anyOf', 'properties', '$defs' 等 Schema 定义元信息）！\n"
            f"2. 只能输出纯 JSON 数据对象（以 {{ 开头、以 }} 结尾），绝对不要用 markdown 代码块包裹！\n"
            f"3. 确保所有的双引号、括号、逗号等符号完美匹配，数值字段必须为纯数字，不可附带文字单位。"
        )
        
        extracted_dict = self.generate_structured_json(fallback_prompt, temperature=temperature)
        
        # 3. 智能根节点解包 (Auto-Unwrap Root Key) 机制
        if isinstance(extracted_dict, dict):
            expected_fields = set(schema_cls.model_fields.keys()) if hasattr(schema_cls, "model_fields") else set(schema_cls.__fields__.keys())
            # 如果当前字典的顶层不包含 Schema 期望的字段，检查是否被大模型在最外层包装了一层 root key
            if not any(field in extracted_dict for field in expected_fields):
                # 检查常见的大模型包装 Key（已剔除 "properties"，防止误解包 Schema 元数据）
                candidates = [schema_cls.__name__, schema_cls.__name__.lower(), "data", "result", "output", "response"]
                unwrapped = False
                for cand in candidates:
                    if cand in extracted_dict and isinstance(extracted_dict[cand], dict):
                        logger.info(f"💡 检测到大模型外层包装 Key '{cand}'，正在自动解包...")
                        extracted_dict = extracted_dict[cand]
                        unwrapped = True
                        break
                # 如果没有匹配到常用名称，但顶层只有唯一的 1 个 Key 且值也是字典（避开 properties 键），自动解包该 Key
                if not unwrapped and len(extracted_dict) == 1:
                    single_key = list(extracted_dict.keys())[0]
                    single_val = list(extracted_dict.values())[0]
                    if isinstance(single_val, dict) and single_key != "properties":
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

    def generate_embeddings(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = True
    ) -> list[list[float]]:
        """
        为给定的文本列表生成嵌入向量 (Embeddings)。
        返回 1024 维的 BGE-M3 向量列表。
        支持针对多切片自动按 batch_size 分批生成并实时打印进度日志。
        """
        if not texts:
            return []

        try:
            embeddings_model = self._get_embeddings_model()
            total_texts = len(texts)

            # 少量文本直接生成并推送 100% 进度
            if total_texts <= batch_size:
                res = embeddings_model.embed_documents(texts)
                if show_progress:
                    try:
                        from app.worker.tasks import emit_agent_log
                        emit_agent_log(
                            log_type="info",
                            content=f"🧮 [BGE-M3 向量化计算] 已完成 {total_texts}/{total_texts} (100%) | 单批计算完成",
                            extra={
                                "type": "embedding_progress",
                                "processed_count": total_texts,
                                "total_texts": total_texts,
                                "percent": 100.0,
                                "current_batch": 1,
                                "total_batches": 1
                            }
                        )
                    except Exception:
                        pass
                return res

            total_batches = (total_texts + batch_size - 1) // batch_size
            if show_progress:
                logger.info(
                    f"🧮 开始分批生成 {total_texts} 个切片的 Embedding 向量 (批次大小: {batch_size}, 共 {total_batches} 批)..."
                )

            all_embeddings: list[list[float]] = []
            
            # 使用 tqdm 生成终端动态进度条 (配合 defensive import 容错)
            try:
                from tqdm import tqdm
                use_tqdm = show_progress
            except ImportError:
                use_tqdm = False

            batch_iterable = range(total_batches)
            if use_tqdm:
                batch_iterable = tqdm(
                    batch_iterable,
                    desc="🧮 [Embedding 向量计算]",
                    unit="批",
                    total=total_batches,
                    ncols=100
                )

            for i in batch_iterable:
                start_idx = i * batch_size
                end_idx = min((i + 1) * batch_size, total_texts)
                batch_texts = texts[start_idx:end_idx]

                batch_result = embeddings_model.embed_documents(batch_texts)
                all_embeddings.extend(batch_result)

                if show_progress:
                    processed_count = len(all_embeddings)
                    percent = (processed_count / total_texts) * 100
                    logger.info(
                        f"📊 [Embedding 进度] 已完成 {processed_count}/{total_texts} ({percent:.1f}%) | 批次 {i + 1}/{total_batches}"
                    )
                    try:
                        from app.worker.tasks import emit_agent_log
                        emit_agent_log(
                            log_type="info",
                            content=f"🧮 [BGE-M3 向量化计算] 已生成 {processed_count}/{total_texts} ({percent:.0f}%) | 批次 {i + 1}/{total_batches}",
                            extra={
                                "type": "embedding_progress",
                                "processed_count": processed_count,
                                "total_texts": total_texts,
                                "percent": round(percent, 1),
                                "current_batch": i + 1,
                                "total_batches": total_batches
                            }
                        )
                    except Exception:
                        pass

            return all_embeddings
        except Exception as e:
            logger.error(f"Embedding 生成失败: {str(e)}")
            raise e

# 暴露单例实例供外部模块直接引用
llm_service = LLMService()
