from sqlalchemy import String, Text, ForeignKey, Integer, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from .base import TenantBase

class QualificationMetadata(TenantBase):
    __tablename__ = "qualification_metadata"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    min_registered_capital_wuyuan: Mapped[float | None] = mapped_column(Float, comment="最低注册资本要求（万元）")
    credit_and_legal_reqs: Mapped[list | None] = mapped_column(JSON, comment="信用与合规要求")
    mandatory_qualifications: Mapped[list | None] = mapped_column(JSON, comment="强制性企业资质门槛")
    system_certifications: Mapped[list | None] = mapped_column(JSON, comment="体系认证/特种许可")
    personnel_requirements: Mapped[list | None] = mapped_column(JSON, comment="核心人员要求明细")
    performance_requirements: Mapped[list | None] = mapped_column(JSON, comment="历史同类业绩门槛")
    bonus_qualifications: Mapped[list | None] = mapped_column(JSON, comment="资质/业绩/人员加分项")
    
    invalid_bid_clauses: Mapped[list | None] = mapped_column(JSON, comment="无效投标/否决投标条款")
    project_annulment_clauses: Mapped[list | None] = mapped_column(JSON, comment="项目废标条款")
    
class FinancialMetadata(TenantBase):
    __tablename__ = "financial_metadata"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    budget: Mapped[dict | None] = mapped_column(JSON, comment="总预算")
    max_price_limit: Mapped[dict | None] = mapped_column(JSON, comment="最高限价")
    sub_package_budgets: Mapped[list | None] = mapped_column(JSON, comment="分包预算明细")
    unit_price_limits: Mapped[dict | None] = mapped_column(JSON, comment="单价控制价")
    provisional_sum: Mapped[dict | None] = mapped_column(JSON, comment="暂列金额")
    contract_price_type: Mapped[str | None] = mapped_column(String(255), comment="计价方式")
    tax_rate_requirement: Mapped[str | None] = mapped_column(String(255), comment="税率要求")
    bid_bond: Mapped[dict | None] = mapped_column(JSON, comment="投标保证金")
    performance_bond: Mapped[dict | None] = mapped_column(JSON, comment="履约保证金")
    warranty_bond: Mapped[dict | None] = mapped_column(JSON, comment="质保金")
    advance_payment_ratio: Mapped[float | None] = mapped_column(Float, comment="预付款比例")
    payment_milestones: Mapped[list | None] = mapped_column(JSON, comment="付款节点")
    price_adjustment_clause: Mapped[str | None] = mapped_column(Text, comment="调价机制")
    delayed_payment_penalty: Mapped[str | None] = mapped_column(Text, comment="违约金条款")

class TimelineMetadata(TenantBase):
    __tablename__ = "timeline_metadata"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    project_id_code: Mapped[str | None] = mapped_column(String(255), comment="项目编号/招标编号")
    project_name: Mapped[str | None] = mapped_column(String(255), comment="项目名称")
    tender_segment: Mapped[str | None] = mapped_column(String(255), comment="标段/包件名称")
    acquisition_info: Mapped[dict | None] = mapped_column(JSON, comment="招标文件领购渠道")
    contacts: Mapped[list | None] = mapped_column(JSON, comment="联系人明细")
    bid_deadline: Mapped[str | None] = mapped_column(String(255), comment="开标截止时间")
    bid_validity_days: Mapped[int | None] = mapped_column(Integer, comment="投标有效期天数")
    tender_milestones: Mapped[list | None] = mapped_column(JSON, comment="关键节点明细列表")
    document_requirements: Mapped[dict | None] = mapped_column(JSON, comment="标书装订要求")
    construction_period_days: Mapped[int | None] = mapped_column(Integer, comment="工期天数")
    construction_period_description: Mapped[str | None] = mapped_column(Text, comment="工期描述原文")

class EngineeringMetadata(TenantBase):
    __tablename__ = "engineering_metadata"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    main_equipment_list: Mapped[list | None] = mapped_column(JSON, comment="主要设备及材料清单")
    special_working_conditions: Mapped[list | None] = mapped_column(JSON, comment="特殊/恶劣实施工况")
    site_environment_constraints: Mapped[str | None] = mapped_column(Text, comment="现场环境与施工限制说明")
    mandatory_standards: Mapped[list | None] = mapped_column(JSON, comment="强制性技术标准")
    tech_validation: Mapped[dict | None] = mapped_column(JSON, comment="样品及POC演示要求")
    safety_and_env_requirements: Mapped[list | None] = mapped_column(JSON, comment="安全生产与文明施工要求")

class EvaluationMetadata(TenantBase):
    __tablename__ = "evaluation_metadata"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    evaluation_method: Mapped[str | None] = mapped_column(String(255), comment="评标方法")
    total_score: Mapped[float | None] = mapped_column(Float, comment="总分")
    weight_distribution: Mapped[dict | None] = mapped_column(JSON, comment="各评分维度及其对应的权重分值")
    score_tree: Mapped[list | None] = mapped_column(JSON, comment="动态评分标准列表")
    hard_service_requirements: Mapped[dict | None] = mapped_column(JSON, comment="售后/硬性约束提取")
