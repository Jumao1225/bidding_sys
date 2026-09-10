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

# LLM 和视觉模型必须绑定到租户数据库配置，不能使用全局密钥。
LLM_MODEL_CONFIG_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "LLM_MODEL_NAME",
)
VLM_MODEL_CONFIG_KEYS = (
    "ALI_VLM_API_KEY",
    "ALI_VLM_API_BASE",
    "ALI_VLM_MODEL_NAME",
)
# MinerU 暂时允许沿用 .env 中的默认 Token 和服务地址。
MINERU_MODEL_CONFIG_KEYS = (
    "MINERU_API_TOKEN",
    "MINERU_API_BASE_URL",
)


class ModelConfigService:
    """管理租户级模型配置，并仅为 MinerU 保留全局默认值兜底。"""

    def get_values(self, tenant_id: Optional[str] = None) -> Dict[str, str]:
        """读取当前租户的运行配置；没有租户时只返回 MinerU 默认值。"""
        effective_tenant_id = tenant_id or current_tenant_id.get()
        if not effective_tenant_id:
            return self._get_mineru_default_values()
        return self.get_effective_values(effective_tenant_id)

    def get_tenant_values(self, tenant_id: str) -> Dict[str, str]:
        """只读取指定租户数据库记录，不读取任何全局模型密钥。"""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id 不能为空")

        values = {key: "" for key in MODEL_CONFIG_KEYS}
        with SessionLocal() as db:
            config = db.query(TenantModelConfig).filter(TenantModelConfig.tenant_id == tenant_id).first()
            if config is None:
                return values

            for key in MODEL_CONFIG_KEYS:
                values[key] = str(getattr(config, key, "") or "").strip()
        return values

    def get_effective_values(self, tenant_id: str) -> Dict[str, str]:
        """读取租户配置，并只用 .env 补齐 MinerU 空值。"""
        values = self.get_tenant_values(tenant_id)
        global_values = self._get_global_values()
        for key in MINERU_MODEL_CONFIG_KEYS:
            if not values[key].strip():
                values[key] = global_values.get(key, "")
        return values

    def get_missing_keys(self, tenant_id: str, required_keys: tuple[str, ...]) -> list[str]:
        """返回指定租户缺失的必填配置项名称。"""
        values = self.get_tenant_values(tenant_id)
        return [key for key in required_keys if not values.get(key, "").strip()]

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
        """读取 .env 中的默认配置，仅供 MinerU 兜底使用。"""
        return {key: str(getattr(settings, key, "") or "") for key in MINERU_MODEL_CONFIG_KEYS}

    def _get_mineru_default_values(self) -> Dict[str, str]:
        """生成无租户上下文时可使用的 MinerU 默认配置。"""
        global_values = self._get_global_values()
        return {
            key: global_values.get(key, "") if key in MINERU_MODEL_CONFIG_KEYS else ""
            for key in MODEL_CONFIG_KEYS
        }

    @staticmethod
    def _invalidate_tenant_runtime_cache(tenant_id: str) -> None:
        """清理指定租户的 LLM 客户端缓存，下一次调用时按新配置创建。"""
        from app.services.llm_service import llm_service

        llm_service.invalidate_tenant_cache(tenant_id)


model_config_service = ModelConfigService()
