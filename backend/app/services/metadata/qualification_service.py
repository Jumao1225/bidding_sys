from typing import Optional, Any
from pydantic import BaseModel, Field

from .base import BaseMetadataService
from app.db.models.metadata import QualificationMetadata

class PersonnelRequirement(BaseModel):
    """核心人员资格要求"""
    role: str = Field(..., description="岗位名称，如：项目经理、技术负责人、安全员")
    cert_name: str = Field(..., description="证书名称及等级，如：一级建造师（电子与智能化）、PMP")
    count: int = Field(1, description="要求人数")
    is_mandatory: bool = Field(True, description="是否为硬性门槛（True为废标项，False为加分项）")
    other_requirements: Optional[str] = Field(None, description="其他要求（如：具备5年以上同类项目经验、提供近6个月社保证明）")

class PerformanceRequirement(BaseModel):
    """历史业绩结构化门槛（方便 Agent 按照条件检索业绩库）"""
    time_frame_years: Optional[int] = Field(None, description="年限要求（如近3年，填入纯数字 3）")
    min_amount_wuyuan: Optional[float] = Field(None, description="单项合同最低金额门槛（单位：万元，如 500.0）")
    required_count: int = Field(1, description="要求的同类业绩最少数量（如 2 个）")
    keyword_or_domain: Optional[str] = Field(None, description="业绩领域/关键字（如：智慧园区、法务 RAG、数据中台）")
    description: str = Field(..., description="业绩要求完整原文说明")

class QualificationSchema(BaseModel):
    # --- 1. 基础准入与信用合规（一票否决项）---
    min_registered_capital_wuyuan: Optional[float] = Field(None, description="最低注册资本要求（万元）")
    credit_and_legal_reqs: list[str] = Field(
        default_factory=list, 
        description="信用与合规要求（如：无重大违法记录、无失信被执行记录、提供近一年财务审计报告）"
    )

    # --- 2. 企业资质与体系认证 ---
    mandatory_qualifications: list[str] = Field(
        default_factory=list, 
        description="强制性企业资质门槛（不满足即废标，如：建筑电子与智能化工程专业承包一级）"
    )
    system_certifications: list[str] = Field(
        default_factory=list, 
        description="体系认证/特种许可（如：ISO9001、ISO27001、安全生产许可证、CMMI3及以上）"
    )

    # --- 3. 核心人员资格 ---
    personnel_requirements: list[PersonnelRequirement] = Field(
        default_factory=list, 
        description="核心人员及证书匹配要求明细"
    )

    # --- 4. 历史业绩门槛 ---
    performance_requirements: list[PerformanceRequirement] = Field(
        default_factory=list, 
        description="历史同类业绩门槛（已结构化，供商务 Agent 检索）"
    )

    # --- 5. 资质加分项说明（非废标项）---
    bonus_qualifications: list[str] = Field(
        default_factory=list, 
        description="资质/业绩/人员方面的评分加分项（如：多提供1份业绩加2分）"
    )

    # --- CoT 推导过程 ---
    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")


class QualificationService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=QualificationMetadata)

    def extract_metadata(self, context: str, document_id: str) -> QualificationSchema:
        system_prompt = """
你是资深的【招投标法务合规官与资质审核专家】。你的任务是从传入的招标文件上下文中，极为精准地提炼出**资格合规与资质门槛**相关的约束条件。
下游的商务 Agent 将基于你的提取结果去公司资质库和业绩库中匹配原件，因此你的提取结果必须客观、精准。

【全局视野与提取指南】
1. **区分废标项与加分项**：仔细甄别上下文，明确指出哪些是“不满足即废标”的强制性条件（存入 mandatory_qualifications 或将人员/业绩的 is_mandatory 设为 True），哪些是“有则加分，无则不废标”的优选条件（存入 bonus_qualifications 或将 is_mandatory 设为 False）。
2. **结构化人员要求**：对于人员证书，必须剥离出人员角色（role）、证书全称及等级（cert_name）、要求数量（count）以及是否是废标项（is_mandatory）。
3. **结构化业绩要求**：针对历史业绩，提取核心数字。如“近3年”，则 `time_frame_years=3`；如“不少于500万”，则 `min_amount_wuyuan=500.0`。如果业绩要求中还写明了特定领域，填入 `keyword_or_domain`。必须保留 `description` 原文。
4. **信用与准入**：提取任何关于“信用中国”、“失信被执行人”、“重大违法记录”、“注册资本金”相关的硬性门槛。
5. **系统认证**：把 ISO、CMMI、特种安全许可证等放入 `system_certifications`。

请先在 `reasoning` 字段中简述你的推断过程，梳理各条件是属于“基本门槛”还是“加分项”，然后再严格按照 Schema 填充。
如果上下文中没有任何关于某项的具体要求，对应字段置空或返回空列表。绝不可凭空捏造。
"""
        return self.extract(context, QualificationSchema, system_prompt, document_id)

qualification_service = QualificationService()
