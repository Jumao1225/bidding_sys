from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .base import BaseMetadataService
from app.db.models.metadata import QualificationMetadata

class QualificationSchema(BaseModel):
    industry_qualifications: Optional[list[str]] = Field(
        None, description="特定行业资质门槛，如建筑业企业资质、电力工程资质、测绘资质等。需提取完整的资质名称和要求的等级。若无则置null"
    )
    special_licenses: Optional[list[str]] = Field(
        None, description="特种许可证，如安全生产许可证、特种设备制造许可证、承装(修、试)电力设施许可证，以及隐性门槛(如ISO体系认证)等。若无则置null"
    )
    core_personnel_certs: Optional[Dict[str, Any]] = Field(
        None, description="核心人员证书要求，严格采用 {'岗位名称': '证书名称及等级要求'} 的格式，例如 {'项目经理': '机电工程一级注册建造师及B证'}。若无则置null"
    )
    historical_performance_reqs: Optional[str] = Field(
        None, description="历史业绩门槛，如要求近3年内有同类项目业绩，金额不少于X万，容量不少于XMw等核心约束参数。若无则置null"
    )
    reasoning: Optional[str] = Field(
        None, description="你的推导与思考过程（CoT），说明你是如何从原文中找到上述要求的。"
    )

class QualificationService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=QualificationMetadata)

    def extract_metadata(self, context: str, document_id: str) -> QualificationSchema:
        system_prompt = """
你是资深的【招投标法务合规官与资质审核专家】。你的任务是从传入的招标文件上下文中，极为精准地提炼出**资格合规与资质门槛**相关的约束条件。
下游的商务 Agent 将基于你的提取结果去公司资质库和业绩库中匹配原件，因此你的提取结果必须100%客观、精准，不可遗漏硬性条件，更不可凭空捏造。

【提取指南】
1. 行业资质：重点寻找带有“资质等级”、“资质要求”、“具备”等字眼的内容，例如“具备电力工程施工总承包叁级及以上资质”，请提取为完整的字符串列表。
2. 特种许可证：重点寻找安全相关的硬性许可，特别是“安全生产许可证”，以及隐性的“ISO9001质量管理体系认证”等。提取为完整的字符串列表。
3. 核心人员：寻找“项目经理”、“技术负责人”相关的段落，强制输出为 `{"岗位名称": "具体证书及要求"}` 的严格键值对。
4. 历史业绩：寻找类似“自xxxx年x月x日以来完成过”、“同类项目业绩”的表述，提取一段精炼的纯文本描述核心时间和规模门槛。

请先在 `reasoning` 字段中简述你的推断过程，然后再严格按照 Schema 填充。
如果上下文中没有任何关于某项的具体要求，请严格将该字段输出为 null。
"""
        return self.extract(context, QualificationSchema, system_prompt, document_id)

qualification_service = QualificationService()
