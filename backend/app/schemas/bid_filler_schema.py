"""
标书数据装配与 Agent 填报核查 Schema 定义

包含公司档案入参、Agent 填报追溯审计核查条目 (FillingAuditItem) 及 API 响应模型。
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class CompanyProfile(BaseModel):
    """投标人公司基本信息档案"""
    company_name: str = Field(default="", description="投标人公司全称")
    legal_representative: str = Field(default="", description="法定代表人姓名")
    authorized_delegate: str = Field(default="", description="授权委托代理人姓名")
    credit_code: str = Field(default="", description="统一社会信用代码")
    registered_address: str = Field(default="", description="公司注册地址")
    contact_phone: str = Field(default="", description="联系电话")
    email: str = Field(default="", description="电子邮箱")
    bank_name: str = Field(default="", description="开户银行名称")
    bank_account: str = Field(default="", description="银行账号")


class AgentFillPlanItem(BaseModel):
    """Agent 针对单个原文待填字段生成的受控填报计划"""
    target_field: str = Field(description="原始 Word 中的待填字段标识")
    source_type: Literal[
        "company_profile",
        "qualification",
        "financial_price",
        "project_timeline",
        "unresolved",
    ] = Field(default="unresolved", description="允许使用的数据源类型")
    source_key: str = Field(default="", description="查询工具使用的业务字段或原文要求")
    requires_uppercase: bool = Field(default=False, description="是否需要人民币大写金额")
    should_fill: bool = Field(default=True, description="原文明确要求填写时为 true")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Agent 对字段理解的置信度")
    reasoning: str = Field(default="", description="Agent 基于原文做出的字段判断理由")


class BidFillPlan(BaseModel):
    """Agent 读取原始 Word 后生成的完整填报计划"""
    fields: List[AgentFillPlanItem] = Field(default_factory=list)
    agent_summary: str = Field(default="", description="Agent 对本次填报计划的摘要")


class FillingAuditItem(BaseModel):
    """Agent 填报对齐追溯审计条目"""
    target_field: str = Field(description="模板待填字段/位置名称")
    raw_requirement: str = Field(default="", description="招标文件/模版原始要求")
    format_style: str = Field(default="常规", description="格式转化说明（如：中文大写金额 / 下划线保留 / 数字）")
    tool_called: str = Field(description="Agent 调用的 Tool 名称")
    data_source_table: str = Field(description="数据库来源数据表与列名")
    db_raw_value: str = Field(description="从数据库中查出的原始真实值")
    final_filled_value: str = Field(description="Agent 转化为最终填入 Word 的文本")
    alignment_status: str = Field(default="✅ 100% 对齐", description="对齐置信度与对齐状态说明")
    has_underline: bool = Field(default=False, description="原处是否有下划线格式")
    source_type: str = Field(default="unknown", description="Agent 选择的数据源类型")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Agent 对字段理解的置信度")
    agent_reasoning: str = Field(default="", description="Agent 对原文语义的判断理由")


class ReviewFinding(BaseModel):
    """深度质检审查发现条目（由 Review Engine 各管线产出）"""
    rule_id: str = Field(description="审查管线规则 ID（如 R1-UNFILLED、R3-SUM-MISMATCH）")
    severity: Literal["error", "warning", "info"] = Field(
        default="info", description="严重级别：error（必须修正）、warning（建议修正）、info（参考信息）"
    )
    path: str = Field(default="N/A", description="问题所在的 Word XPath 路径")
    description: str = Field(default="", description="人类可读的问题描述")
    current_value: str = Field(default="", description="当前填写值")
    expected_value: str = Field(default="", description="期望值（如有）")
    auto_fixable: bool = Field(default=False, description="是否可被自动修正")
    fix_proposal: Optional[Dict[str, Any]] = Field(
        default=None, description="自动修正方案（修正后的 proposal 字典）"
    )


class BidFillRequest(BaseModel):
    """标书自动填报 API 请求入参"""
    company_profile: Optional[CompanyProfile] = Field(
        default_factory=CompanyProfile, description="自定义投标人档案（不传则使用系统默认公司数据）"
    )
    custom_instructions: Optional[str] = Field(
        default=None,
        description="全局自定义填写指令（会注入到每个 Worker 子 Agent 的提示词中）。"
                    "例如：'所有日期统一填写为 YYYY年MM月DD日'、'投标总价按 XXX 折报价'"
    )
    category_hints: Optional[Dict[str, str]] = Field(
        default=None,
        description="按章节类别的额外指令（key 为 category 或 mapping_hint，value 为额外指令）。"
                    "例如：{'pricing': '报价表中所有单价上浮 X%', 'bid_letter': '投标函落款日期填 YYYY年MM月DD日'}"
    )


class BidFillAuditReport(BaseModel):
    """Agent 填报核查报告"""
    document_id: str
    total_fields_count: int = 0
    audit_items: List[FillingAuditItem] = Field(default_factory=list)
    review_findings: List[ReviewFinding] = Field(
        default_factory=list, description="深度质检审查发现列表"
    )
    review_summary: str = Field(
        default="", description="质检审查摘要统计（如: 2 errors, 3 warnings, 5 infos）"
    )
    summary_note: str = ""

