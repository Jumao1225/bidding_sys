import uuid
from sqlalchemy import String, Date, Float
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date
from .base import Base, TenantBase

class CompanyQualification(TenantBase):
    __tablename__ = "company_qualifications"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(500))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    file_url: Mapped[str | None] = mapped_column(String(500))

class MarketPriceReference(TenantBase):
    __tablename__ = "market_price_references"

    item_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100), comment="品牌")
    spec: Mapped[str | None] = mapped_column(String(255), comment="规格")
    model: Mapped[str | None] = mapped_column(String(100), comment="型号")
    manufacturer: Mapped[str | None] = mapped_column(String(255), comment="生产厂商")
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500), comment="备注")


from datetime import datetime, timezone
from sqlalchemy import String, Date, Float, DateTime

class CompanyProfileModel(Base):
    __tablename__ = "company_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 企业档案允许先创建空记录，待管理员在企业档案页面补充完整信息。
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_representative: Mapped[str | None] = mapped_column(String(100))
    authorized_delegate: Mapped[str | None] = mapped_column(String(100))
    credit_code: Mapped[str | None] = mapped_column(String(100))
    registered_address: Mapped[str | None] = mapped_column(String(500))
    contact_phone: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(100))
    bank_name: Mapped[str | None] = mapped_column(String(255))
    bank_account: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))



