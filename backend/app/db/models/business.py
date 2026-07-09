from sqlalchemy import String, Date, Float
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date
from .base import TenantBase

class CompanyQualification(TenantBase):
    __tablename__ = "company_qualifications"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str | None] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    file_url: Mapped[str | None] = mapped_column(String(500))

class MarketPriceReference(TenantBase):
    __tablename__ = "market_price_references"

    item_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100))
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
