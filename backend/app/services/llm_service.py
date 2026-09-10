import json
import hashlib
from typing import Optional, Dict, Any, Type, TypeVar
from loguru import logger
from pydantic import BaseModel
from tenacity import retry, wait_exponential, stop_after_attempt

from app.core.config import settings
from app.services.audit_service import audit_service
from app.services.model_config_service import LLM_MODEL_CONFIG_KEYS
from app.services.model_capabilities import resolve_model_capabilities


class ModelUnavailableError(RuntimeError):
    """表示模型未配置、无法创建客户端或模型服务调用失败。"""


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
        # 启动阶段不再使用 .env 中的 LLM 密钥创建全局客户端，模型必须绑定当前租户。
        self._global_is_configured = False
        self._llm_cache = {}
        self.embeddings = None
        self.raw_llm = None
        self.llm = None
        logger.info("LLM 服务已初始化，等待读取租户级模型配置。")

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
        # 运行时客户端也必须在具体请求中按租户懒加载，避免不同租户共用全局客户端。
        self._global_is_configured = False
        self.raw_llm = None
        self.llm = None
        logger.info("LLM 运行时缓存已清理，后续请求将按租户配置重新创建客户端。")

    @property
    def is_configured(self) -> bool:
        """按当前请求租户判断 LLM 是否配置完成。"""
        return not self._get_missing_llm_config_keys()

    def is_configured_for_tenant(self, tenant_id: Optional[str]) -> bool:
        """显式判断指定租户是否配置了 LLM。"""
        return not self._get_missing_llm_config_keys(tenant_id)

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

    def _get_runtime_values(self, tenant_id: Optional[str] = None) -> Dict[str, str]:
        """读取指定租户的有效模型配置；未指定时才使用当前上下文租户。"""
        from app.core.context import current_tenant_id
        from app.services.model_config_service import model_config_service

        effective_tenant_id = tenant_id or current_tenant_id.get()
        return model_config_service.get_values(effective_tenant_id)

    def _get_missing_llm_config_keys(self, tenant_id: Optional[str] = None) -> list[str]:
        """检查指定租户的大模型配置是否完整，并返回缺失项。"""
        runtime_values = self._get_runtime_values(tenant_id)
        return [
            key for key in LLM_MODEL_CONFIG_KEYS
            if not str(runtime_values.get(key, "") or "").strip()
        ]

    def _ensure_llm_configured(self, tenant_id: Optional[str] = None) -> None:
        """在必须调用大模型的链路上拦截缺失配置并返回可操作提示。"""
        missing_keys = self._get_missing_llm_config_keys(tenant_id)
        if not missing_keys:
            return

        missing_labels = {
            "OPENAI_API_KEY": "API Key",
            "OPENAI_API_BASE": "API 地址",
            "LLM_MODEL_NAME": "模型名称",
        }
        missing_text = "、".join(missing_labels[key] for key in missing_keys)
        logger.warning(
            "租户 {} 尚未配置完整的大模型参数，缺少: {}",
            tenant_id or "当前上下文租户",
            missing_text,
        )
        raise ModelUnavailableError(
            f"模型不可用：当前租户尚未配置完整的大模型参数，请前往“模型配置”填写 {missing_text}"
        )

    def get_llm(
        self,
        temperature: float = 0.3,
        json_mode: bool = False,
        tenant_id: Optional[str] = None,
        max_retries: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        """
        根据指定的租户、temperature 和 json_mode 返回缓存的大模型实例。
        如果不存在，则动态创建一个并缓存。
        """
        from app.core.context import current_tenant_id

        effective_tenant_id = tenant_id or current_tenant_id.get()
        runtime_values = self._get_runtime_values(effective_tenant_id)
        if self._get_missing_llm_config_keys(effective_tenant_id):
            return None

        cache_tenant_id = effective_tenant_id or "global"
        generation_options = self._get_generation_options(
            runtime_values,
            max_output_tokens=max_output_tokens,
            json_mode=json_mode,
        )
        config_fingerprint = hashlib.sha256(
            (
                f"{runtime_values['OPENAI_API_KEY']}\0{runtime_values['OPENAI_API_BASE']}\0"
                f"{runtime_values['LLM_MODEL_NAME']}\0{json.dumps(generation_options, sort_keys=True)}"
            ).encode()
        ).hexdigest()[:16]
        effective_max_retries = 3 if max_retries is None else max(0, int(max_retries))
        cache_key = (
            f"{cache_tenant_id}:{config_fingerprint}:"
            f"{temperature}_{json_mode}_{effective_max_retries}_{max_output_tokens or 'default'}"
        )
        if cache_key not in self._llm_cache:
            try:
                from langchain_openai import ChatOpenAI
                self._log_runtime_config(cache_tenant_id, runtime_values)
                # 防御性限制超时配置，避免非法值导致客户端立即失败或永久等待。
                request_timeout = max(
                    1.0,
                    float(getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 900.0)),
                )
                logger.info(
                    "LLM 请求超时配置已启用: timeout_seconds={}, max_retries={}",
                    request_timeout,
                    effective_max_retries,
                )
                llm = ChatOpenAI(
                    model_name=runtime_values["LLM_MODEL_NAME"],
                    api_key=runtime_values["OPENAI_API_KEY"],
                    base_url=runtime_values["OPENAI_API_BASE"] if runtime_values["OPENAI_API_BASE"] else None,
                    temperature=temperature,
                    request_timeout=request_timeout,  # 显式配置请求超时，防止网络卡死
                    # ChatAgent 会传入 0，由上层统一向 SSE 报告重试进度；其他调用默认保留 3 次。
                    max_retries=effective_max_retries,
                    **generation_options,
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

    @staticmethod
    def _get_generation_options(
        runtime_values: Dict[str, str],
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """将应用层统一的输出上限转换为各模型兼容的请求参数。"""
        capabilities = resolve_model_capabilities(
            model_name=runtime_values.get("LLM_MODEL_NAME"),
            base_url=runtime_values.get("OPENAI_API_BASE"),
        )
        # 所有供应商统一使用同一个应用层上限，避免不同模型出现不同的默认配置。
        configured_limit = max(1, int(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 50000)))
        effective_limit = configured_limit if max_output_tokens is None else max(1, int(max_output_tokens))

        if capabilities.provider == "deepseek":
            thinking_enabled = bool(getattr(settings, "DEEPSEEK_THINKING_ENABLED", False))
            # LangChain 新版本会把 max_tokens 改写为 max_completion_tokens；DeepSeek 要求使用 max_tokens，
            # 所以将该参数放入 extra_body，由 OpenAI 兼容客户端原样合并到请求体中。
            extra_body: Dict[str, Any] = {"max_tokens": effective_limit}
            extra_body["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}
            logger.info(
                "请求参数已启用: model={}, max_output_tokens={}, wire_parameter=max_tokens, thinking={}",
                runtime_values.get("LLM_MODEL_NAME", ""),
                effective_limit,
                "enabled" if thinking_enabled else "disabled",
            )
            return {"extra_body": extra_body}

        if capabilities.provider == "glm":
            configured_thinking_enabled = bool(getattr(settings, "GLM_THINKING_ENABLED", True))
            # 仅结构化 JSON 请求关闭思考；普通聊天仍尊重 GLM 聊天思考开关，避免改变用户可见表达能力。
            thinking_enabled = configured_thinking_enabled and not json_mode
            clear_thinking = bool(getattr(settings, "GLM_CLEAR_THINKING", True))
            # GLM 兼容接口使用 max_tokens；通过 extra_body 保留字段名称，避免 LangChain 改写为 max_completion_tokens。
            extra_body = {
                "max_tokens": effective_limit,
                "thinking": {
                    "type": "enabled" if thinking_enabled else "disabled",
                    "clear_thinking": clear_thinking,
                },
            }
            logger.info(
                "GLM 请求参数已启用: model={}, json_mode={}, max_output_tokens={}, wire_parameter=max_tokens, thinking={}, clear_thinking={}",
                runtime_values.get("LLM_MODEL_NAME", ""),
                json_mode,
                effective_limit,
                "enabled" if thinking_enabled else "disabled",
                clear_thinking,
            )
            return {"extra_body": extra_body}

        # 未识别的私有兼容网关暂不主动注入输出上限，避免未知字段导致兼容性回退。
        logger.info(
            "请求参数调整: model={}, 未识别供应商参数，交由服务端默认策略处理",
            runtime_values.get("LLM_MODEL_NAME", ""),
        )
        return {}

    @staticmethod
    def _log_runtime_config(tenant_id: str, runtime_values: Dict[str, str]) -> None:
        """记录脱敏后的运行配置，禁止将完整 API Key 写入日志。"""
        api_key = runtime_values.get("OPENAI_API_KEY", "")
        key_suffix = api_key[-4:] if len(api_key) >= 4 else ("已配置" if api_key else "未配置")
        logger.info(
            "LLM 客户端配置已加载: tenant_id={}, model={}, base_url={}, api_key_suffix={}",
            tenant_id,
            runtime_values.get("LLM_MODEL_NAME", ""),
            runtime_values.get("OPENAI_API_BASE", ""),
            key_suffix,
        )

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

    def _execute_generate_structured_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        tenant_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        底层结构化 JSON 生成执行逻辑（不带重试装饰器）。
        发送 Prompt 并期望返回 JSON 格式的结构化数据。
        """
        self._ensure_llm_configured(tenant_id)
            
        # 结构化调用由本服务层的 tenacity 统一重试，关闭客户端内部重试，避免重试叠加。
        llm = self.get_llm(
            temperature=temperature,
            json_mode=True,
            tenant_id=tenant_id,
            max_retries=0,
            max_output_tokens=max_output_tokens,
        )
        if llm is None:
            raise ModelUnavailableError("模型不可用：无法创建模型客户端")
            
        try:
            import time
            import re
            start_time = time.time()
            try:
                response = llm.invoke(prompt)
            except Exception as model_error:
                audit_service.log_event(
                    action_type="llm_call",
                    status="error",
                    error_message=f"ModelUnavailableError: {model_error}",
                )
                logger.exception("模型服务调用失败，模型不可用: {}", model_error)
                raise ModelUnavailableError(
                    "模型不可用：模型服务连接失败，请检查模型地址、网络或服务状态"
                ) from model_error
            end_time = time.time()
            content = response.content
            
            # 提取 Token 消耗
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
                token_usage = response.response_metadata['token_usage']
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)

            finish_reason = getattr(response, "response_metadata", {}).get("finish_reason")
            if finish_reason == "length":
                logger.warning(
                    "⚠️ LLM 返回内容达到长度上限，JSON 可能不完整: model={}, prompt_tokens={}, completion_tokens={}",
                    self._get_runtime_values(tenant_id).get("LLM_MODEL_NAME", ""),
                    prompt_tokens,
                    completion_tokens,
                )
                raise ValueError("大模型返回内容达到输出长度上限，JSON 内容不完整，请缩小提取分块后重试")

            exec_time_ms = int((end_time - start_time) * 1000)
            logger.info(
                f"🤖 [LLM 调用完成] ({self._get_runtime_values(tenant_id)['LLM_MODEL_NAME']}) | 耗时: {exec_time_ms}ms | "
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
        except ModelUnavailableError:
            raise
        except json.JSONDecodeError as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=f"JSONDecodeError: {str(e)}")
            logger.error(f"❌ 大模型返回内容解析 JSON 失败: {str(e)}, 原始返回片段: {content[:300] if 'content' in locals() else 'None'}")
            raise ValueError(f"大模型返回内容解析 JSON 失败: {str(e)}")
        except Exception as e:
            audit_service.log_event(action_type="llm_call", status="error", error_message=str(e))
            logger.error(f"❌ LLM 调用过程发生异常: {str(e)}")
            raise e

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _retry_generate_structured_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        tenant_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """带 3 次指数退避重试机制的结构化 JSON 生成包装。"""
        return self._execute_generate_structured_json(
            prompt=prompt,
            temperature=temperature,
            tenant_id=tenant_id,
            max_output_tokens=max_output_tokens,
        )

    def generate_structured_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        tenant_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        skip_retry: bool = False,
    ) -> Dict[str, Any]:
        """
        发送 Prompt 并期望返回 JSON 格式的结构化数据。
        支持传入自定义温度 (默认 0.3) 与自定义输出 Token 上限。
        支持 skip_retry: 设为 True 时单次尝试失败立即抛出异常，便于业务层快速触发降级兜底。
        如果未配置 API Key，直接抛出异常，不再提供 Mock 数据兜底。
        """
        if skip_retry:
            return self._execute_generate_structured_json(
                prompt=prompt,
                temperature=temperature,
                tenant_id=tenant_id,
                max_output_tokens=max_output_tokens,
            )
        return self._retry_generate_structured_json(
            prompt=prompt,
            temperature=temperature,
            tenant_id=tenant_id,
            max_output_tokens=max_output_tokens,
        )

    # 保持 __wrapped__ 指向底层单次执行方法，兼容绕过重试的单元测试
    generate_structured_json.__wrapped__ = _execute_generate_structured_json

    # 兼容便捷别名
    generate_json = generate_structured_json

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.3,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        发送 Prompt 并返回纯文本生成结果。
        """
        self._ensure_llm_configured(tenant_id)

        llm = self.get_llm(
            temperature=temperature,
            json_mode=False,
            tenant_id=tenant_id,
            max_retries=0,
        )
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
                f"🤖 [LLM 文本生成完成] ({self._get_runtime_values(tenant_id)['LLM_MODEL_NAME']}) | 耗时: {exec_time_ms}ms | "
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
    def generate_structured_output(
        self,
        prompt: str,
        schema_cls: Type[BaseModel],
        temperature: float = 0.1,
        tenant_id: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> BaseModel:
        """
        利用大模型原生的 Structured Outputs 能力直接生成校验过的 Pydantic 对象。
        如果当前模型(如某些兼容 API)不支持，则平滑降级到 json_mode 并手动反序列化，
        并具备智能外层包装节点 (Root Key Unwrap) 解包能力。
        """
        self._ensure_llm_configured(tenant_id)
            
        import time
        
        # 1. 解析当前模型能力，国内兼容网关统一优先走 JSON Mode。
        # GLM 官方 Chat Completions 的稳定结构化协议是 json_object；原生 json_schema
        # 会被部分私有网关拒绝，因此不再为 GLM 额外发起一次必然失败的请求。
        runtime_values = self._get_runtime_values(tenant_id)
        capabilities = resolve_model_capabilities(
            model_name=runtime_values.get("LLM_MODEL_NAME"),
            base_url=runtime_values.get("OPENAI_API_BASE"),
        )
        
        if capabilities.provider not in {"deepseek", "glm"}:
            llm_raw = self.get_llm(
                temperature=temperature,
                json_mode=False,
                tenant_id=tenant_id,
                max_retries=0,
                max_output_tokens=max_output_tokens,
            )
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
                logger.warning(
                    "Native Structured Output 失败，自动降级到 JSON Mode: provider={}, error={}",
                    capabilities.provider,
                    e,
                )
        
        # 2. 国内模型统一走 JSON Mode + Schema 注入，避免重复尝试不兼容的原生协议。
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
        
        extracted_dict = self.generate_structured_json(
            fallback_prompt,
            temperature=temperature,
            tenant_id=tenant_id,
            max_output_tokens=max_output_tokens,
            # 外层 generate_structured_output 已负责重试，避免 JSON 调用再嵌套 3 次重试。
            skip_retry=True,
        )
        
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
    def expand_query(
        self,
        query: str,
        num_variants: int = 3,
        temperature: float = 0.7,
        tenant_id: Optional[str] = None,
    ) -> list[str]:
        """
        多路查询重写 (Query Expansion)。
        利用 LLM 将单一关键词扩展为多个相关的语义变体。
        使用较高的 temperature (默认 0.7) 来增加发散性。
        """
        if not self._get_runtime_values(tenant_id).get("OPENAI_API_KEY"):
            return [query]
            
        llm = self.get_llm(
            temperature=temperature,
            json_mode=True,
            tenant_id=tenant_id,
            max_retries=0,
        )
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

    async def astream_chat(
        self,
        messages: list,
        temperature: float = 0.7,
        tenant_id: Optional[str] = None,
    ):
        """
        异步流式聊天接口，专为 ChatPanel 打字机效果设计。
        基于 LangChain astream() 逐 token 推送，DeepSeek 模型完全兼容。

        Args:
            messages: LangChain 消息格式列表，如 [SystemMessage(...), HumanMessage(...)]
            temperature: 生成温度，聊天场景建议 0.7

        Yields:
            str: 每次推送的 token 片段
        """
        self._ensure_llm_configured(tenant_id)

        # 聊天场景不需要 json_mode，使用普通 raw LLM 实例
        llm = self.get_llm(
            temperature=temperature,
            json_mode=False,
            tenant_id=tenant_id,
            max_retries=0,
        )
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
