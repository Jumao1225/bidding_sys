from typing import Dict, Mapping, Optional

from loguru import logger

from app.core.config import settings
from app.core.context import current_tenant_id
from app.db.models.model_config import TenantModelConfig
from app.db.session import SessionLocal


MODEL_CONFIG_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "LLM_MODEL_NAME",
    "MINERU_API_TOKEN",
    "MINERU_API_BASE_URL",
    "ALI_VLM_API_KEY",
    "ALI_VLM_API_BASE",
    "ALI_VLM_MODEL_NAME",
)


class ModelConfigService:
    """管理租户级模型配置，并为没有覆盖配置的租户提供全局默认值。"""

    def get_values(self, tenant_id: Optional[str] = None) -> Dict[str, str]:
        """读取当前上下文租户的有效配置。"""
        effective_tenant_id = tenant_id or current_tenant_id.get()
        if not effective_tenant_id:
            return self._get_global_values()
        return self.get_effective_values(effective_tenant_id)

    def get_effective_values(self, tenant_id: str) -> Dict[str, str]:
        """读取租户覆盖值，并用旧 .env 配置补齐空值。"""
        values = self._get_global_values()
        with SessionLocal() as db:
            config = db.query(TenantModelConfig).filter(TenantModelConfig.tenant_id == tenant_id).first()
            if config:
                for key in MODEL_CONFIG_KEYS:
                    configured_value = getattr(config, key, "") or ""
                    if configured_value.strip():
                        values[key] = configured_value
        return values

    def update_values(
        self,
        tenant_id: str,
        values: Mapping[str, str],
        updated_by_user_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """保存指定租户的模型配置并清理该租户的 LLM 缓存。"""
        unknown_keys = set(values) - set(MODEL_CONFIG_KEYS)
        if unknown_keys:
            raise ValueError(f"存在不支持的模型配置项: {', '.join(sorted(unknown_keys))}")
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id 不能为空")

        normalized_values = {
            key: str(values.get(key, "") or "").strip()
            for key in MODEL_CONFIG_KEYS
        }
        with SessionLocal() as db:
            config = db.query(TenantModelConfig).filter(TenantModelConfig.tenant_id == tenant_id).first()
            if config is None:
                config = TenantModelConfig(tenant_id=tenant_id)
                db.add(config)
            for key, value in normalized_values.items():
                setattr(config, key, value)
            config.updated_by_user_id = updated_by_user_id
            db.commit()

        self._invalidate_tenant_runtime_cache(tenant_id)
        logger.info("租户 {} 的模型配置已更新，配置项: {}", tenant_id, ", ".join(MODEL_CONFIG_KEYS))
        return self.get_effective_values(tenant_id)

    def _get_global_values(self) -> Dict[str, str]:
        """读取旧 .env 中的全局默认配置。"""
        return {key: str(getattr(settings, key, "") or "") for key in MODEL_CONFIG_KEYS}

    @staticmethod
    def _invalidate_tenant_runtime_cache(tenant_id: str) -> None:
        """清理指定租户的 LLM 客户端缓存，下一次调用时按新配置创建。"""
        from app.services.llm_service import llm_service

        llm_service.invalidate_tenant_cache(tenant_id)


model_config_service = ModelConfigService()
