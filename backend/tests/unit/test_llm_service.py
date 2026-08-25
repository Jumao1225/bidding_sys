from unittest.mock import patch

from app.services.llm_service import LLMService


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


def test_runtime_config_log_should_not_contain_complete_api_key(caplog):
    """运行配置日志只允许记录 API Key 尾部，禁止泄露完整密钥。"""
    service = object.__new__(LLMService)

    with caplog.at_level("INFO"):
        service._log_runtime_config(
            "tenant-a",
            {
                "OPENAI_API_KEY": "secret-api-key-1234",
                "OPENAI_API_BASE": "https://llm.example/v1",
                "LLM_MODEL_NAME": "tenant-model",
            },
        )

    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "1234" in log_text
    assert "secret-api-key-1234" not in log_text
