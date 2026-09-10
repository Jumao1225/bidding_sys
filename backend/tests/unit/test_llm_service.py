from io import StringIO
from unittest.mock import patch

import pytest
from loguru import logger

from app.services.llm_service import LLMService, ModelUnavailableError


def test_get_runtime_values_should_use_explicit_tenant_without_context():
    """显式传入租户时，即使在线程中没有 ContextVar，也必须读取该租户配置。"""
    service = object.__new__(LLMService)

    with patch("app.services.model_config_service.model_config_service.get_values") as get_values_mock:
        get_values_mock.return_value = {
            "OPENAI_API_KEY": "tenant-key",
            "OPENAI_API_BASE": "https://llm.example/v1",
            "LLM_MODEL_NAME": "tenant-model",
        }

        values = service._get_runtime_values("tenant-a")

    get_values_mock.assert_called_once_with("tenant-a")
    assert values["LLM_MODEL_NAME"] == "tenant-model"


def test_generate_structured_json_should_raise_model_unavailable_without_api_key(monkeypatch):
    """未配置模型密钥时，应返回可供接口识别的模型不可用异常。"""
    service = object.__new__(LLMService)
    monkeypatch.setattr(
        service,
        "_get_runtime_values",
        lambda tenant_id=None: {"OPENAI_API_KEY": ""},
    )

    with pytest.raises(ModelUnavailableError, match="模型不可用"):
        LLMService.generate_structured_json.__wrapped__(service, "测试提示词")


def test_generate_structured_json_should_raise_model_unavailable_when_invoke_fails(monkeypatch):
    """模型客户端调用连接失败时，应转换为模型不可用异常。"""
    service = object.__new__(LLMService)
    monkeypatch.setattr(
        service,
        "_get_runtime_values",
        lambda tenant_id=None: {
            "OPENAI_API_KEY": "configured-key",
            "LLM_MODEL_NAME": "test-model",
            "OPENAI_API_BASE": "http://llm.example/v1",
        },
    )

    class FailingModel:
        """抛出连接异常的模型测试替身。"""

        def invoke(self, prompt):
            raise ConnectionError("模型服务连接失败")

    monkeypatch.setattr(service, "get_llm", lambda **kwargs: FailingModel())
    monkeypatch.setattr("app.services.llm_service.audit_service.log_event", lambda **kwargs: None)

    with pytest.raises(ModelUnavailableError, match="模型不可用"):
        LLMService.generate_structured_json.__wrapped__(service, "测试提示词")


def test_runtime_config_log_should_not_contain_complete_api_key():
    """运行配置日志只允许记录 API Key 尾部，禁止泄露完整密钥。"""
    service = object.__new__(LLMService)

    log_stream = StringIO()
    sink_id = logger.add(log_stream, level="INFO")
    try:
        service._log_runtime_config(
            "tenant-a",
            {
                "OPENAI_API_KEY": "secret-api-key-1234",
                "OPENAI_API_BASE": "https://llm.example/v1",
                "LLM_MODEL_NAME": "tenant-model",
            },
        )
        log_text = log_stream.getvalue()
    finally:
        logger.remove(sink_id)
    assert "1234" in log_text
    assert "secret-api-key-1234" not in log_text


def test_get_generation_options_should_use_deepseek_max_tokens_and_disable_thinking(monkeypatch):
    """DeepSeek 请求应使用统一输出上限，并保留 max_tokens 传输兼容性。"""
    monkeypatch.setattr("app.services.llm_service.settings.LLM_MAX_OUTPUT_TOKENS", 200000)
    monkeypatch.setattr("app.services.llm_service.settings.DEEPSEEK_THINKING_ENABLED", False)

    options = LLMService._get_generation_options(
        {
            "LLM_MODEL_NAME": "deepseek-v4-flash",
            "OPENAI_API_BASE": "https://api.deepseek.com",
        }
    )

    assert options == {
        "extra_body": {
            "max_tokens": 200000,
            "thinking": {"type": "disabled"},
        }
    }


def test_get_generation_options_should_honor_per_call_worker_output_limit(monkeypatch):
    """调用方传入的单次输出上限应覆盖所有模型的统一默认值。"""
    monkeypatch.setattr("app.services.llm_service.settings.LLM_MAX_OUTPUT_TOKENS", 200000)
    monkeypatch.setattr("app.services.llm_service.settings.DEEPSEEK_THINKING_ENABLED", False)

    options = LLMService._get_generation_options(
        {
            "LLM_MODEL_NAME": "deepseek-v4-flash",
            "OPENAI_API_BASE": "https://api.deepseek.com",
        },
        max_output_tokens=50000,
    )

    assert options["extra_body"]["max_tokens"] == 50000


def test_get_generation_options_should_apply_generic_output_limit_to_other_model(monkeypatch):
    """非 DeepSeek 模型也应使用统一输出上限和标准 max_completion_tokens 字段。"""
    monkeypatch.setattr("app.services.llm_service.settings.LLM_MAX_OUTPUT_TOKENS", 50000)

    options = LLMService._get_generation_options(
        {
            "LLM_MODEL_NAME": "qwen-model",
            "OPENAI_API_BASE": "https://llm.example/v1",
        }
    )

    assert options == {"max_completion_tokens": 50000}


def test_get_generation_options_should_honor_explicit_generic_output_limit():
    """非 DeepSeek 模型应支持调用方传入的单次输出上限。"""
    options = LLMService._get_generation_options(
        {
            "LLM_MODEL_NAME": "GLM-5.3-Flash",
            "OPENAI_API_BASE": "http://llm.example/v1",
        },
        max_output_tokens=8192,
    )

    assert options == {"max_completion_tokens": 8192}


def test_get_llm_should_pass_deepseek_options_to_chat_openai(monkeypatch):
    """创建 DeepSeek 客户端时，应将专用参数传给 ChatOpenAI。"""
    service = object.__new__(LLMService)
    service._llm_cache = {}
    runtime_values = {
        "OPENAI_API_KEY": "tenant-key",
        "OPENAI_API_BASE": "https://api.deepseek.com",
        "LLM_MODEL_NAME": "deepseek-v4-flash",
    }
    monkeypatch.setattr(service, "_get_runtime_values", lambda tenant_id=None: runtime_values)
    monkeypatch.setattr("app.services.llm_service.settings.LLM_MAX_OUTPUT_TOKENS", 200000)
    monkeypatch.setattr("app.services.llm_service.settings.DEEPSEEK_THINKING_ENABLED", False)

    class FakeChatOpenAI:
        """记录客户端构造参数的测试替身。"""

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def bind(self, **kwargs):
            self.bind_kwargs = kwargs
            return self

    with patch("langchain_openai.ChatOpenAI", FakeChatOpenAI):
        llm = service.get_llm(temperature=0.1, json_mode=True, tenant_id="tenant-a")

    assert llm.kwargs["extra_body"] == {
        "max_tokens": 200000,
        "thinking": {"type": "disabled"},
    }
    assert llm.kwargs["max_retries"] == 3
    assert llm.bind_kwargs == {"response_format": {"type": "json_object"}}


def test_get_llm_should_pass_generic_output_limit_to_chat_openai(monkeypatch):
    """创建非 DeepSeek 客户端时，应将通用输出上限传给 ChatOpenAI。"""
    service = object.__new__(LLMService)
    service._llm_cache = {}
    runtime_values = {
        "OPENAI_API_KEY": "tenant-key",
        "OPENAI_API_BASE": "http://llm.example/v1",
        "LLM_MODEL_NAME": "GLM-5.3-Flash",
    }
    monkeypatch.setattr(service, "_get_runtime_values", lambda tenant_id=None: runtime_values)
    monkeypatch.setattr("app.services.llm_service.settings.LLM_MAX_OUTPUT_TOKENS", 50000)

    class FakeChatOpenAI:
        """记录客户端构造参数的测试替身。"""

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    with patch("langchain_openai.ChatOpenAI", FakeChatOpenAI):
        llm = service.get_llm(temperature=0.1, tenant_id="tenant-a")

    assert llm.kwargs["max_completion_tokens"] == 50000
    assert llm.kwargs["max_retries"] == 3
