import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TenantBase(Base):
    """
    Abstract base class for all tenant-specific models.
    Enforces multi-tenancy at the schema level.
    """
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, comment="租户ID, 多租户SaaS核心隔离字段")
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True, comment="数据创建者用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
