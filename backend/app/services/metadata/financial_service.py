from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .base import BaseMetadataService
from app.db.models.metadata import FinancialMetadata

class PaymentMilestone(BaseModel):
    stage: str = Field(..., description="付款阶段名称，如'预付款', '进度款', '验收款', '质保金'")
    percentage: str = Field(..., description="付款比例，如'30%'")
    condition: str = Field(..., description="付款触发条件，如'合同签订后7个工作日内'")

class FinancialSchema(BaseModel):
    max_price_limit: Optional[str] = Field(
        None, description="最高投标限价（控制价），通常是一个具体的金额数值（如 1,181,380 元），或包含单价限价。若无则置null"
    )
    budget: Optional[str] = Field(
        None, description="项目预算/投资估算额。若无则置null"
    )
    bid_bond_ratio: Optional[str] = Field(
        None, description="投标保证金金额或占投标报价的比例。若无则置null"
    )
    performance_bond_ratio: Optional[str] = Field(
        None, description="履约保证金金额或占中标金额的比例。若无则置null"
    )
    payment_milestones: Optional[list[PaymentMilestone]] = Field(
        None, description="付款节点与结付比例的有序数组，方便前端渲染时间轴。若无则置null"
    )
    reasoning: Optional[str] = Field(
        None, description="你的推导与思考过程（CoT），尤其是对于分批付款比例的加总校验逻辑。"
    )

class FinancialService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=FinancialMetadata)

    def extract_metadata(self, context: str, document_id: str) -> FinancialSchema:
        system_prompt = """
你是资深的【注册造价师与投融资财务专家】。你的任务是从传入的招标文件上下文中，极为精准地提炼出**财务与资金流**相关的核心约束条件。
下游的 Cost Agent（报价计算专家）将会把你的提取结果（特别是最高限价和分批付款比例）作为硬性数学约束，锁死动态调价引擎的上限。因此，你提取的每一个数字和比例都必须绝对准确。

【提取指南】
1. 最高限价与预算：仔细区分“最高限价”（不能超过的红线）与“预算”（预估资金），这两者可能不同，如果有具体的数字请完整提取，包含币种。
2. 保证金：寻找“投标保证金”、“履约保证金”、“质量保证金”的金额或比例（如“中标合同金额的10%”）。
3. 付款节点：仔细梳理商务条款中的资金支付方式。通常包含预付款、进度款、竣工结算款、质保金。请在 `payment_milestones` 中以结构化的**数组**形式提取，必须包含 `stage`（阶段）、`percentage`（比例）和 `condition`（触发条件）。

请在 `reasoning` 字段中首先写下你的推导过程，特别是对资金节点的梳理。
如果上下文中没有任何关于某项的财务指标，请严格将该字段输出为 null，绝对不可瞎编数字。
"""
        return self.extract(context, FinancialSchema, system_prompt, document_id)

financial_service = FinancialService()
