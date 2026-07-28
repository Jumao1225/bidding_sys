from sqlalchemy import String, Text, ForeignKey, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .base import TenantBase

class QualificationMatch(TenantBase):
    __tablename__ = "qualification_matches"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    qualification_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("company_qualifications.id", ondelete="SET NULL"))
    
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    match_level: Mapped[str] = mapped_column(String(50), nullable=False) # GREEN, YELLOW, RED
    ai_reasoning: Mapped[str] = mapped_column(Text, nullable=False)

class RiskItem(TenantBase):
    __tablename__ = "risk_items"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(50), nullable=False) # legal, business, technical
    risk_text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_reasoning: Mapped[str] = mapped_column(Text, nullable=False)

class CostEstimate(TenantBase):
    __tablename__ = "cost_estimates"

    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    reference_price_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("market_price_references.id", ondelete="SET NULL"))
    
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(50), default="台")
    unit_price: Mapped[float | None] = mapped_column(Float, default=0.0, comment="匹配到的参考单价")
    calculated_total: Mapped[float] = mapped_column(Float, nullable=False, comment="单项小计金额")
    brand: Mapped[str | None] = mapped_column(String(255), comment="品牌要求")
    spec: Mapped[str | None] = mapped_column(Text, comment="规格与技术指标")
    remark: Mapped[str | None] = mapped_column(Text, comment="对比分析或预警")


