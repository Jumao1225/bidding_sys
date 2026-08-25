from unittest.mock import patch

import pytest

from app.services.model_config_service import MODEL_CONFIG_KEYS, ModelConfigService


def test_get_model_config_should_return_only_supported_runtime_keys():
    """读取配置时只返回三个模型实际使用的白名单键。"""
    values = ModelConfigService().get_values()

    assert set(values) == set(MODEL_CONFIG_KEYS)
    assert all(isinstance(value, str) for value in values.values())


def test_update_model_config_should_save_tenant_values_without_logging_secrets():
    """更新配置时应写入指定租户记录，并触发该租户缓存刷新。"""
    service = ModelConfigService()
    update_values = {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_API_BASE": "https://llm.example/v1",
        "LLM_MODEL_NAME": "test-llm",
        "MINERU_API_TOKEN": "mineru-token",
        "MINERU_API_BASE_URL": "https://mineru.example/api/v4",
        "ALI_VLM_API_KEY": "vlm-key",
        "ALI_VLM_API_BASE": "https://vlm.example/v1",
        "ALI_VLM_MODEL_NAME": "test-vlm",
    }

    fake_db = type("FakeDb", (), {
        "query": lambda self, *_args: self,
        "filter": lambda self, *_args: self,
        "first": lambda self: None,
        "add": lambda self, obj: setattr(self, "config", obj),
        "commit": lambda self: None,
    })()
    fake_session = type("FakeSession", (), {
        "__enter__": lambda self: fake_db,
        "__exit__": lambda self, *_args: None,
    })()

    with patch("app.services.model_config_service.SessionLocal", return_value=fake_session), \
         patch.object(service, "get_effective_values", return_value=update_values), \
         patch.object(service, "_invalidate_tenant_runtime_cache") as invalidate_mock:
        updated_values = service.update_values("tenant-a", update_values, updated_by_user_id="admin-a")

    assert updated_values == update_values
    assert fake_db.config.tenant_id == "tenant-a"
    assert fake_db.config.LLM_MODEL_NAME == "test-llm"
    assert fake_db.config.updated_by_user_id == "admin-a"
    invalidate_mock.assert_called_once_with("tenant-a")


def test_update_model_config_should_reject_unknown_key():
    """更新配置时应拒绝未纳入白名单的环境变量，避免任意修改后端设置。"""
    with pytest.raises(ValueError, match="不支持的模型配置项"):
        ModelConfigService().update_values("tenant-a", {"DATABASE_URL": "postgresql://invalid"})


def test_update_model_config_should_reject_empty_tenant_id():
    """更新配置时必须提供租户 ID，禁止写入无归属的全局记录。"""
    with pytest.raises(ValueError, match="tenant_id 不能为空"):
        ModelConfigService().update_values("", {})
