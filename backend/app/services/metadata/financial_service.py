import re
from typing import Optional, Dict

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
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
    percentage: Optional[float] = Field(None, description="付款百分比数值（如：30.0 表示 30%）")
    condition: Optional[str] = Field(None, description="付款触发条件原文（如：合同签订并收到预付款保函后7个工作日内）")
    invoice_required: Optional[bool] = Field(True, description="付款前是否需要先开具等额发票")

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


DIRECT_BUDGET_TERMS = ("采购总预算", "采购预算")
GENERIC_BUDGET_TERMS = ("预算金额", "项目总预算", "项目预算", "资金预算")
MAX_PRICE_LIMIT_TERMS = ("最高投标限价", "最高限价", "招标控制价", "投标控制价")
MONEY_VALUE_PATTERN = re.compile(
    r"(?:人民币\s*)?[¥￥]?\s*(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元)?"
)


def _find_money_after_terms(context: str, terms: tuple[str, ...]) -> Optional[float]:
    """从术语所在行提取紧邻金额，避免将后续无关金额误关联到字段。"""
    if not context:
        return None

    term_pattern = "|".join(re.escape(term) for term in terms)
    for term_match in re.finditer(term_pattern, context):
        line_end = context.find("\n", term_match.end())
        candidate_text = context[term_match.end():line_end if line_end >= 0 else None]
        money_match = MONEY_VALUE_PATTERN.search(candidate_text)
        if not money_match:
            continue

        try:
            amount = float(money_match.group("amount").replace(",", ""))
        except ValueError:
            logger.warning("财务定向金额解析失败，术语: {}，文本: {}", term_match.group(), candidate_text[:80])
            continue

        # 无币种和单位的小数字通常是条款编号，不得误判为金额。
        raw_digits = money_match.group("amount").replace(",", "").split(".", 1)[0]
        if not money_match.group("unit") and not candidate_text[:money_match.end()].strip().startswith(("人民币", "¥", "￥")) and len(raw_digits) < 4:
            continue

        if money_match.group("unit") in ("万", "万元"):
            amount *= 10000
        return amount

    return None


def reconcile_core_financial_amounts(result: FinancialSchema, context: str) -> FinancialSchema:
    """以原文中的明确术语校正预算与最高限价，阻止模型跨字段复用金额。"""
    # 明确“采购预算”的业务含义强于泛称“预算金额”，仅在前者缺失时才回退。
    budget_amount = _find_money_after_terms(context, DIRECT_BUDGET_TERMS)
    if budget_amount is None:
        budget_amount = _find_money_after_terms(context, GENERIC_BUDGET_TERMS)
    max_price_limit_amount = _find_money_after_terms(context, MAX_PRICE_LIMIT_TERMS)

    if budget_amount is not None:
        if not result.budget or result.budget.amount != budget_amount:
            logger.info("使用原文明确采购预算校正结构化金额: {} 元", budget_amount)
        result.budget = MoneyAmount(amount=budget_amount)

    if max_price_limit_amount is not None:
        if not result.max_price_limit or result.max_price_limit.amount != max_price_limit_amount:
            logger.info("使用原文明确最高限价校正结构化金额: {} 元", max_price_limit_amount)
        result.max_price_limit = MoneyAmount(amount=max_price_limit_amount)

    return result


class FinancialService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=FinancialMetadata)

    def extract_metadata(
        self,
        context: str,
        document_id: str,
        tenant_id: Optional[str] = None,
    ) -> FinancialSchema:
        system_prompt = """
你是资深的【注册造价师与投融资财务专家】。你的任务是从传入的招标文件上下文中，极为精准地提炼出**财务与资金流**相关的核心约束条件。
下游的 Cost Agent（报价计算引擎）将完全依赖你的结构化数据，特别是单价限价、不可竞争的暂列金以及各项比例，作为硬性数学约束。

【全局视野与提取指南】
1. **零容忍数字幻觉（最高指令）**：系统对数字极其敏感，你提取的任何数字（金额、比例）必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。如果原文是某数值（如 XXX元/万元），绝对不可凭妄想错传或缩放数字。
2. **预算与控制价的分离与包容关系（极度重要）**：
   - **采购预算 (Budget)** 是甲方为整个项目准备的资金池总额。
   - **最高限价/招标控制价 (Max Price Limit)** 是允许投标人报出的最高价格。
   - **两者的关系**：最高限价 **永远小于或等于** 预算。在同一份标书中出现这两个不同的金额是**完全正常**的，**绝不是冲突或笔误！** 
   - 提取策略：如果文中既写了“采购预算为XXX金额（总资金池）”，又在投标邀请或评标办法中写了“最高投标限价为YYY金额（最高限价上限，例如限价打折）”，请将对应的 XXX金额 准确填入 `budget`，将 YYY金额 准确填入 `max_price_limit`。绝对不可以为了数字表面整齐而抹杀弃置其中任何一个！
   - 只有当同一概念（如两个地方都宣称是“最高限价”）出现不同金额时，才适用“优先大写金额、优先核心章节”的冲突处理规则。
   - **逐项回填要求**：必须独立检查并填写 `budget` 与 `max_price_limit`。即使其中一个字段已找到，也绝不能停止查找另一个字段；不得用采购预算填充最高投标限价，也不得用最高投标限价填充采购预算。
   - **同义表述识别**：`采购总预算`、`采购预算`、`项目预算`、`预算金额` 均属于 `budget`；`最高投标限价`、`最高限价`、`招标控制价`、`投标控制价` 均属于 `max_price_limit`。必须以紧邻金额的原文语义为准。
   - **定向证据优先**：上下文中带有“预算/限价定向证据”标识的片段是系统从原文精确定位的关键证据。只要其中出现明确金额，必须优先完成相应字段的提取；两个字段可以来自不同章节。
   - **冲突消解**：当“采购预算/采购总预算”与泛称“预算金额”出现不同金额时，`budget` 必须优先采用带有“采购预算/采购总预算”的明确表述；`max_price_limit` 只能采用紧邻最高限价、最高投标限价、招标控制价或投标控制价的金额，绝不允许复制预算金额。
3. **警惕暂列金与单价控制价**：必须找出文中所有“暂估价”、“暂列金额”，剥离到 provisional_sum。同时关注单价限制（如：综合单价不得超过XXX金额/元），填入 unit_price_limits。
4. **资金形式量化**：对于三大保证金，提取其金额或比例描述，计算出纯数字（如果原文给了基数的话），并明确支持的缴纳形式（如：电汇、电子保函）。
5. **数字转化与核对**：将百分比全部转化为浮点数（如 10% 存为 10.0）。确保 `amount` 统一单位为“元”（如原为万元须精确换算折抵至元单位）。在落库前，你必须在心里复核一遍数字是否与原文绝对一致。
6. **付款节点**：提取付款触发阶段（stage）、比例（percentage）和是否需要发票（invoice_required）。

请在 `reasoning` 字段中首先写下你的推导过程。如果发现多个金额冲突，必须在 reasoning 中明确指出两处的金额，并解释你采纳哪一个的理由。最后一步，你必须在 reasoning 中声明你已经核对了所有提取出的数字，确保与原文绝对一致。
如果上下文中没有任何关于某项的财务指标，请严格将该字段输出为 null，绝对不可瞎编数字。
"""
        result = self.extract(
            context,
            FinancialSchema,
            system_prompt,
            document_id,
            tenant_id=tenant_id,
            persist=False,
        )
        result = reconcile_core_financial_amounts(result, context)

        if document_id:
            try:
                self._save_to_db(document_id, result)
            except SQLAlchemyError:
                logger.exception("财务元数据校正后落库失败，文档ID: {}", document_id)

        return result

financial_service = FinancialService()
