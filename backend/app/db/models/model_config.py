from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TenantModelConfig(Base):
    """租户级模型配置，一条租户记录对应一套独立 API。"""

    __tablename__ = "tenant_model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    OPENAI_API_KEY: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    OPENAI_API_BASE: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    LLM_MODEL_NAME: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    MINERU_API_TOKEN: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    MINERU_API_BASE_URL: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    ALI_VLM_API_KEY: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    ALI_VLM_API_BASE: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    ALI_VLM_MODEL_NAME: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
