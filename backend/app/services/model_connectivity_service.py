"""模型运行时接口的轻量连通性探测服务。"""

from time import perf_counter
from typing import Any, Dict, Literal
from uuid import uuid4

import requests
from loguru import logger

from app.services.model_capabilities import resolve_model_capabilities


ModelType = Literal["llm", "mineru", "vlm"]


class ModelConnectivityService:
    """按模型类型发送最小探测请求，不修改租户配置也不记录密钥。"""

    _REQUEST_TIMEOUT = (5.0, 20.0)
    _MODEL_LABELS = {
        "llm": "主语言模型",
        "mineru": "MinerU 文档 OCR 模型",
        "vlm": "视觉模型",
    }

    def test(
        self,
        model_type: ModelType,
        api_key: str,
        api_base: str,
        model_name: str = "",
        tenant_id: str | None = None,
    ) -> Dict[str, Any]:
        """执行指定模型的最小请求并返回统一结构的可用性结果。"""
        normalized_api_key = api_key.strip()
        normalized_api_base = api_base.strip().rstrip("/")
        normalized_model_name = model_name.strip()

        logger.info(
            "开始测试租户 {} 的{}接口，模型={}，地址={}",
            tenant_id or "当前",
            self._MODEL_LABELS.get(model_type, model_type),
            normalized_model_name or "未提供",
            self._safe_url_for_log(normalized_api_base),
        )

        if model_type in {"llm", "vlm"}:
            return self._test_chat_model(
                model_type=model_type,
                api_key=normalized_api_key,
                api_base=normalized_api_base,
                model_name=normalized_model_name,
            )
        if model_type == "mineru":
            return self._test_mineru(
                api_key=normalized_api_key,
                api_base=normalized_api_base,
            )
        return self._build_result(model_type, False, "不支持的模型类型", 0, normalized_model_name)

    def _test_chat_model(
        self,
        model_type: Literal["llm", "vlm"],
        api_key: str,
        api_base: str,
        model_name: str,
    ) -> Dict[str, Any]:
        """使用 OpenAI 兼容 Chat Completions 接口完成最小文本探测。"""
        label = self._MODEL_LABELS[model_type]
        missing_fields = []
        if not api_key:
            missing_fields.append("API Key")
        if not api_base:
            missing_fields.append("API 地址")
        if not model_name:
            missing_fields.append("模型名称")
        if missing_fields:
            return self._build_result(
                model_type,
                False,
                f"请先填写{label}的{'、'.join(missing_fields)}",
                0,
                model_name,
            )

        started_at = perf_counter()
        try:
            capabilities = resolve_model_capabilities(model_name=model_name, base_url=api_base)
            probe_payload: dict[str, Any] = {
                "model": model_name,
                "messages": [{"role": "user", "content": "请仅回复：连接成功"}],
                "temperature": 0,
                "max_tokens": 8,
            }
            if capabilities.provider in {"deepseek", "glm"}:
                # 国内模型同时验证 JSON Mode 和显式关闭思考，避免“普通文本可用但业务结构化调用失败”。
                probe_payload["messages"] = [
                    {"role": "user", "content": '请仅返回 JSON：{"status":"ok"}'}
                ]
                probe_payload["response_format"] = {"type": "json_object"}
                probe_payload["thinking"] = {"type": "disabled"}

            response = requests.post(
                f"{api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=probe_payload,
                timeout=self._REQUEST_TIMEOUT,
            )
        except requests.Timeout:
            logger.warning("{}接口测试超时，地址={}", label, self._safe_url_for_log(api_base))
            return self._build_result(model_type, False, f"{label}请求超时，请检查地址和网络", started_at, model_name)
        except requests.RequestException as request_error:
            logger.warning("{}接口测试网络异常，异常类型={}", label, type(request_error).__name__)
            return self._build_result(model_type, False, f"无法连接{label}，请检查地址和网络", started_at, model_name)

        if not 200 <= response.status_code < 300:
            message = self._message_for_http_error(response.status_code, label)
            logger.warning("{}接口返回 HTTP {}", label, response.status_code)
            return self._build_result(model_type, False, message, started_at, model_name)

        try:
            response_payload = response.json()
        except ValueError:
            logger.warning("{}接口返回了无法解析的 JSON", label)
            return self._build_result(model_type, False, f"{label}返回格式异常，请检查兼容接口配置", started_at, model_name)

        choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
        if not isinstance(choices, list) or not choices:
            logger.warning("{}接口响应缺少 choices 字段", label)
            return self._build_result(model_type, False, f"{label}响应格式异常，未返回有效结果", started_at, model_name)

        logger.info("{}接口测试成功，模型={}，耗时={}ms", label, model_name, self._elapsed_ms(started_at))
        return self._build_result(
            model_type,
            True,
            f"接口可用，已收到模型 {model_name} 的响应",
            started_at,
            model_name,
        )

    def _test_mineru(self, api_key: str, api_base: str) -> Dict[str, Any]:
        """查询随机任务 ID，验证 MinerU API 可达且不会创建解析任务。"""
        if not api_key:
            return self._build_result("mineru", False, "请先填写 MinerU API Token", 0, None)
        if not api_base:
            return self._build_result("mineru", False, "请先填写 MinerU API 地址", 0, None)

        started_at = perf_counter()
        probe_batch_id = str(uuid4())
        try:
            response = requests.get(
                f"{api_base}/extract-results/batch/{probe_batch_id}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                timeout=self._REQUEST_TIMEOUT,
            )
        except requests.Timeout:
            logger.warning("MinerU 接口测试超时，地址={}", self._safe_url_for_log(api_base))
            return self._build_result("mineru", False, "MinerU 请求超时，请检查地址和网络", started_at, None)
        except requests.RequestException as request_error:
            logger.warning("MinerU 接口测试网络异常，异常类型={}", type(request_error).__name__)
            return self._build_result("mineru", False, "无法连接 MinerU，请检查地址和网络", started_at, None)

        if response.status_code in {401, 403}:
            logger.warning("MinerU 接口鉴权失败，HTTP {}", response.status_code)
            return self._build_result("mineru", False, "MinerU Token 无效或没有访问权限", started_at, None)
        if response.status_code >= 500:
            logger.warning("MinerU 服务端异常，HTTP {}", response.status_code)
            return self._build_result("mineru", False, f"MinerU 服务暂时不可用（HTTP {response.status_code}）", started_at, None)

        try:
            response_payload = response.json()
        except ValueError:
            logger.warning("MinerU 接口返回了无法解析的 JSON，HTTP {}", response.status_code)
            return self._build_result("mineru", False, "MinerU 地址未返回 API JSON，请检查是否填写了 /api/v4", started_at, None)

        # 随机任务不存在时，MinerU 可能返回业务错误或 404；这两种情况仍证明请求已到达 API，且没有创建任务。
        if not isinstance(response_payload, dict):
            return self._build_result("mineru", False, "MinerU 返回格式异常，请检查 API 地址", started_at, None)
        if not any(key in response_payload for key in ("code", "msg", "data")):
            logger.warning("MinerU 接口返回了非 MinerU API 格式，HTTP {}", response.status_code)
            return self._build_result("mineru", False, "MinerU 地址未返回预期 API 响应，请检查是否填写了 /api/v4", started_at, None)
        logger.info("MinerU 接口测试成功，未创建解析任务，耗时={}ms", self._elapsed_ms(started_at))
        return self._build_result(
            "mineru",
            True,
            "接口可用，Token 已通过鉴权（未创建解析任务）",
            started_at,
            None,
        )

    @staticmethod
    def _message_for_http_error(status_code: int, label: str) -> str:
        """把上游 HTTP 状态转换为不泄露响应正文的诊断文案。"""
        if status_code in {401, 403}:
            return f"{label} API Key 无效或没有访问权限"
        if status_code == 404:
            return f"{label}接口地址或模型名称不存在"
        if status_code == 429:
            return f"{label}请求受到频率限制，请稍后重试"
        return f"{label}返回 HTTP {status_code}，请检查配置"

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        """计算耗时并保证返回非负整数。"""
        if not started_at:
            return 0
        return max(0, int((perf_counter() - started_at) * 1000))

    @classmethod
    def _build_result(
        cls,
        model_type: ModelType,
        available: bool,
        message: str,
        started_at: float,
        model_name: str | None,
    ) -> Dict[str, Any]:
        """组装统一探测结果，供 API schema 做最终校验。"""
        return {
            "model_type": model_type,
            "model_name": model_name or None,
            "available": available,
            "latency_ms": cls._elapsed_ms(started_at),
            "message": message,
        }

    @staticmethod
    def _safe_url_for_log(api_base: str) -> str:
        """日志仅保留地址主体，避免把查询参数中的敏感信息写入日志。"""
        if not api_base:
            return "<empty>"
        return api_base.split("?", 1)[0]


model_connectivity_service = ModelConnectivityService()
