from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .base import BaseMetadataService
from app.db.models.metadata import EvaluationMetadata

class EvaluationSchema(BaseModel):
    price_weight: Optional[int] = Field(
        None, description="评标办法中的价格（商务）权重分值，必须是纯整数（如 30）。若无则置null"
    )
    tech_weight: Optional[int] = Field(
        None, description="评标办法中的技术权重分值，必须是纯整数（如 50）。若无则置null"
    )
    warranty_years: Optional[str] = Field(
        None, description="质保运维年限或缺陷责任期要求，如“2年”。若无则置null"
    )
    after_sales_response_hours: Optional[int] = Field(
        None, description="售后响应时限硬性指标，必须提取纯数字的小时数（如 24）。若无则置null"
    )
    penalty_clauses: Optional[list[str]] = Field(
        None, description="性能未达标、工期延误的扣罚索赔条款。输出字符串数组。若无则置null"
    )
    reasoning: Optional[str] = Field(
        None, description="你的推导与思考过程（CoT），说明如何找到和总结分值权重及违约罚则的。"
    )

class EvaluationService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EvaluationMetadata)

    def extract_metadata(self, context: str, document_id: str) -> EvaluationSchema:
        system_prompt = """
你是【资深评标专家与售后运维总监】。你的任务是从传入的招标文件（通常是“评标办法”和“合同商务条款”部分）上下文中，提取出**评分权重分布与售后罚则约束**。
下游的 Service Worker（售后服务专家）会直接把诸如“4小时内答复”等硬指标转化为最终标书中的《服务承诺函》，以确保100%正向响应，一字不差。

【提取指南】
1. 评分权重：在“评标办法”章节中寻找“价格分”、“技术分”的占比说明。必须提取出纯整数（例如 30），代表分数或百分比。
2. 售后时限：在“售后服务要求”章节中，寻找“响应时间”。必须提取纯数字（代表小时），如“4小时内答复”提取为 4。
3. 质保期限：寻找“缺陷责任期”、“质保期”的时间长度。
4. 罚则条款：在“违约责任”章节寻找延期罚款、性能扣罚等索赔条款，提炼为字符串数组。

请在 `reasoning` 字段中首先写下你的提取定位与逻辑。
如果上下文中没有任何对应的评分标准、售后时限或罚金条款，请务必将其对应的字段输出为 null，绝不可以主观推断或编造。
"""
        return self.extract(context, EvaluationSchema, system_prompt, document_id)

evaluation_service = EvaluationService()
