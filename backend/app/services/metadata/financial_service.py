from typing import Optional, Dict
from pydantic import BaseModel, Field

from .base import BaseMetadataService
from app.db.models.metadata import FinancialMetadata

class MoneyAmount(BaseModel):
    """资金金额统一结构（纯数字，方便 Agent 逻辑判断与计算）"""
    amount: float = Field(..., description="数值金额（单位：元），如 5000000.0")
    currency: str = Field("CNY", description="币种，默认 CNY（人民币）")
    amount_in_words: Optional[str] = Field(None, description="大写金额（如：伍佰万元整）")

class SubPackageBudget(BaseModel):
    """多标包/分包预算明细"""
    package_name: str = Field(..., description="标包/标段名称或编号（如：'包1：硬件设备采购'）")
    budget: MoneyAmount = Field(..., description="该标包的采购预算/控制价")

class BondInfo(BaseModel):
    """保证金明细（投标/履约/质保）"""
    amount_description: str = Field(..., description="招标文件原文描述（如：'合同额的 2%'、'固定 10 万元'）")
    calculated_amount: Optional[float] = Field(None, description="换算出的纯数字金额（单位：元），方便比对")
    acceptable_forms: Optional[list[str]] = Field(
        default_factory=lambda: ["现金转账", "银行保函", "电子保函"], 
        description="允许的缴纳形式"
    )
    refund_condition: Optional[str] = Field(None, description="退还节点/条件（如：未中标人开标后5个工作日内退还）")

class PaymentMilestone(BaseModel):
    """付款节点与现金流结构"""
    stage: str = Field(..., description="付款阶段名称（如：预付款、进度款、初验收款、终验收款、质保金）")
    percentage: float = Field(..., description="付款百分比数值（如：30.0 表示 30%）")
    condition: str = Field(..., description="付款触发条件原文（如：合同签订并收到预付款保函后7个工作日内）")
    invoice_required: bool = Field(True, description="付款前是否需要先开具等额发票")

class FinancialSchema(BaseModel):
    # --- 1. 预算与控制价红线 (Cost Agent 报价防爆核心) ---
    budget: Optional[MoneyAmount] = Field(None, description="项目总采购预算/资金来源总额")
    max_price_limit: Optional[MoneyAmount] = Field(None, description="最高投标限价/招标控制价（总价上限，超限即废标）")
    
    sub_package_budgets: Optional[list[SubPackageBudget]] = Field(
        default_factory=list, 
        description="多标包/分包项目的各包预算明细（若分包采购）"
    )
    unit_price_limits: Optional[dict[str, float]] = Field(
        default_factory=dict, 
        description="关键品目/人月/单价控制价限制字典，如 {'高级工程师人月单价': 35000.0}"
    )
    provisional_sum: Optional[MoneyAmount] = Field(
        None, 
        description="暂列金额/不可预见费（不可竞争费用，所有投标人需原样计入总价）"
    )

    # --- 2. 计价方式与税率要求 ---
    contract_price_type: Optional[str] = Field(
        None, 
        description="合同计价方式（如：固定总价、固定单价、可调总价、单价与总价结合）"
    )
    tax_rate_requirement: Optional[str] = Field(None, description="税率要求（如：13% 增值税专用发票、6% 服务费专票）")

    # --- 3. 三大保证金（资金占用成本）---
    bid_bond: Optional[BondInfo] = Field(None, description="投标保证金详情")
    performance_bond: Optional[BondInfo] = Field(None, description="履约保证金详情")
    warranty_bond: Optional[BondInfo] = Field(None, description="质量保证金/缺陷责任金详情")

    # --- 4. 资金流与付款节点 ---
    advance_payment_ratio: Optional[float] = Field(0.0, description="预付款比例（如 10.0 表示 10%）")
    payment_milestones: Optional[list[PaymentMilestone]] = Field(default_factory=list, description="付款阶段明细")
    
    # --- 5. 财务风控与违约补偿条款 ---
    price_adjustment_clause: Optional[str] = Field(None, description="调价机制/原材料上涨补偿条款说明")
    delayed_payment_penalty: Optional[str] = Field(None, description="甲方迟延付款的利息/违约金补偿条款")

    # --- 推导过程 ---
    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")


class FinancialService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=FinancialMetadata)

    def extract_metadata(self, context: str, document_id: str) -> FinancialSchema:
        system_prompt = """
你是资深的【注册造价师与投融资财务专家】。你的任务是从传入的招标文件上下文中，极为精准地提炼出**财务与资金流**相关的核心约束条件。
下游的 Cost Agent（报价计算引擎）将完全依赖你的结构化数据，特别是单价限价、不可竞争的暂列金以及各项比例，作为硬性数学约束。

【全局视野与提取指南】
1. **零容忍数字幻觉（最高指令）**：系统对数字极其敏感，你提取的任何数字（金额、比例）必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。如果原文是 135 万，绝对不能写成其他数字。
2. **预算与控制价的分离与包容关系（极度重要）**：
   - **采购预算 (Budget)** 是甲方为整个项目准备的资金池总额。
   - **最高限价/招标控制价 (Max Price Limit)** 是允许投标人报出的最高价格。
   - **两者的关系**：最高限价 **永远小于或等于** 预算。在同一份标书中出现这两个不同的金额是**完全正常**的，**绝不是冲突或笔误！** 
   - 提取策略：如果文中既写了“采购预算为135万”，又在投标邀请或评标办法中写了“最高投标限价为1181380元”，请将 1350000 填入 `budget`，将 1181380 填入 `max_price_limit`。绝对不可以为了统一数字而抹杀另一个！
   - 只有当同一概念（如两个地方都宣称是“最高限价”）出现不同金额时，才适用“优先大写金额、优先核心章节”的冲突处理规则。
3. **警惕暂列金与单价控制价**：必须找出文中所有“暂估价”、“暂列金额”，剥离到 provisional_sum。同时关注单价限制（如：综合单价不得超过X元），填入 unit_price_limits。
4. **资金形式量化**：对于三大保证金，提取其金额或比例描述，计算出纯数字（如果原文给了基数的话），并明确支持的缴纳形式（如：电汇、电子保函）。
5. **数字转化与核对**：将百分比全部转化为浮点数（如 10% 存为 10.0）。确保 `amount` 统一单位为“元”（如 135万 存为 1350000.0）。在落库前，你必须在心里复核一遍数字是否与原文绝对一致。
6. **付款节点**：提取付款触发阶段（stage）、比例（percentage）和是否需要发票（invoice_required）。

请在 `reasoning` 字段中首先写下你的推导过程。如果发现多个金额冲突，必须在 reasoning 中明确指出两处的金额，并解释你采纳哪一个的理由。最后一步，你必须在 reasoning 中声明你已经核对了所有提取出的数字，确保与原文绝对一致。
如果上下文中没有任何关于某项的财务指标，请严格将该字段输出为 null，绝对不可瞎编数字。
"""
        return self.extract(context, FinancialSchema, system_prompt, document_id)

financial_service = FinancialService()
