from sqlalchemy import String, Text, ForeignKey, Float, Integer, JSON
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
    item_code: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="前端 BOM 项目编码")
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(50), default=None, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, default=0.0, comment="匹配到的参考单价")
    calculated_total: Mapped[float] = mapped_column(Float, nullable=False, comment="单项小计金额")
    brand: Mapped[str | None] = mapped_column(String(255), comment="品牌要求/匹配品牌")
    model: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="前端 BOM 型号")
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="生产厂家/制造厂商")
    spec: Mapped[str | None] = mapped_column(Text, comment="规格与技术指标")
    spec_requirement: Mapped[str | None] = mapped_column(Text, nullable=True, comment="招标文件规格要求原文")
    matched_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="价格库匹配名称")
    matched_brand: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="价格库匹配品牌")
    matched_model: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="价格库匹配型号")
    matched_manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="价格库匹配生产厂家")
    key_parameters: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="关键参数")
    brand_requirements: Mapped[str | None] = mapped_column(Text, nullable=True, comment="招标文件品牌/产地要求")
    match_quality: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="匹配质量")
    warning: Mapped[str | None] = mapped_column(Text, nullable=True, comment="价格匹配预警")
    comparison_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="价格对比说明")
    parent_item: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="直接父级设备")
    root_item: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="顶层标的物")
    tree_level: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="BOM 层级")
    per_set_qty: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单套定额数量")
    per_set_quantity: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单套定额数量兼容字段")
    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="所属标段/区域/分项工程")
    remark: Mapped[str | None] = mapped_column(Text, comment="BOM 清单备注，与投标报价表备注列对齐")
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True, comment="前端 BOM 原始顺序")
