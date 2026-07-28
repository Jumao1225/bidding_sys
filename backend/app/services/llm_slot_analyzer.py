"""
大模型纯自主槽位识别与感知识别引擎 (llm_slot_analyzer.py)

功能：
通过纯大模型 (LLM) 对 Office CLI 读取到的 Word 文档 DOM 结构文本进行全文深度阅读与语义感知，
自动识别出所有需填报的空白槽位、下划线、括号占位符、留空表格单元格及自然语言填报要求，
并输出带 XML 物理 Path、前导 Label 与业务 Intent 的结构化 Task 清单。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints 类型提示；
3. 使用 loguru 进行超详细日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from app.services.llm_service import llm_service


class SlotItem(BaseModel):
    """单条识别出的空白槽位结构描述"""
    path: str = Field(description="Word DOM 节点物理 Path，例如 '/body/p[12]' 或 '/body/tbl[1]/tr[2]/tc[1]'")
    run_index: Optional[int] = Field(default=None, description="段落内的目标 Run 索引（若是段落原位替换）")
    label: str = Field(description="前导上下文或引导标签文本，例如 '投标人名称：'、'统一社会信用代码：'")
    raw_placeholder: str = Field(description="原文中的占位符模式，例如 '______'、'【 】'、'空单元格'")
    target_field_intent: str = Field(
        description="大模型推理出的业务字段 Intent (如 'company_name', 'credit_code', 'legal_representative', 'authorized_delegate', 'bank_name', 'bank_account', 'registered_address', 'contact_phone', 'email', 'project_name', 'project_code', 'bid_price_numeric', 'bid_price_chinese', 'construction_period', 'qualification_cert')"
    )
    confidence_score: float = Field(default=1.0, description="大模型识别置信度 (0.0 ~ 1.0)")
    reasoning: str = Field(description="大模型选择该 Intent 的分析推理过程")


class SlotAnalysisReport(BaseModel):
    """槽位分析报告总输出"""
    total_slots_found: int = Field(description="识别出的总空白槽位数量")
    slots: List[SlotItem] = Field(default_factory=list, description="具体识别出的槽位清单")
    summary: str = Field(description="对本文档填报难易度与关键字段分布的总体分析总结")


SLOT_ANALYZER_SYSTEM_PROMPT = """
你是一位顶级的招投标文书专家与 Word DOM 结构分析引擎。
你现在的任务是：仔细阅读以下由 Office CLI 提取出的《投标文件格式》Word 文档全量文本与 DOM 节点结构，
自主寻找并识别出所有需要投标人填写的空白槽位、占位符及留空单元格。

【可识别的槽位类型包括】：
1. 下划线填空：例如 `投标人名称：______` 或 `法定代表人：________________`
2. 括号占位符：例如 `统一社会信用代码：【 】` 或 `[此处填写注册地址]`
3. 表格留空单元格：表格左侧为字段名称（如 `开户银行`），右侧或下方单元格文本为空。
4. 自然语言说明指示：例如 `【注：请在此处填入投标人近三年财务状况总览】`

【常用业务字段 Intent 分类参考】：
- `company_name`: 投标人全称/公司名称
- `legal_representative`: 法定代表人/法人代表
- `authorized_delegate`: 授权代表/被授权人/签字代表
- `credit_code`: 统一社会信用代码/税号/注册号
- `registered_address`: 注册地址/公司住所
- `contact_phone`: 联系电话/手机号
- `email`: 电子邮箱/E-mail
- `bank_name`: 开户银行/基本户开户行
- `bank_account`: 银行账号/基本户账号
- `project_name`: 招标项目名称
- `project_code`: 招标编号/项目编号
- `bid_price_numeric`: 投标总价(小写/数字)
- `bid_price_chinese`: 投标总价(大写金额)
- `construction_period`: 工期/交货期/服务期
- `warranty_period`: 质保期/保修期
- `qualification_cert`: 资质证书/ISO认证/软著

请输出结构化的分析报告，包含每个槽位的绝对 Path、Label、占位符样式及选定的 Intent。
对于非填空段落（如普通的承诺书正文或标题），请勿误判为槽位。
"""


def analyze_slots_with_llm(doc_structure_str: str) -> SlotAnalysisReport:
    """
    使用大模型纯自主识别 Word 结构文本中的全量空白槽位。

    :param doc_structure_str: Office CLI query_structure 返回的 JSON/文本 DOM 结构
    :return: SlotAnalysisReport 槽位识别报告
    """
    logger.info("====== [LLM Slot Analyzer] 启动大模型纯自主槽位感知识别引擎 ======")
    
    if not doc_structure_str or not doc_structure_str.strip():
        logger.warning("[LLM Slot Analyzer] 传入的文档结构文本为空，直接返回空报告")
        return SlotAnalysisReport(
            total_slots_found=0,
            slots=[],
            summary="输入文档结构为空，未识别到任何槽位。"
        )

    logger.debug(f"[LLM Slot Analyzer] 待分析文档结构文本长度: {len(doc_structure_str)} 字符")

    prompt = f"{SLOT_ANALYZER_SYSTEM_PROMPT}\n\n【待分析的 Word 文档 DOM 结构文本】:\n\"\"\"\n{doc_structure_str}\n\"\"\"\n"

    try:
        logger.info("[LLM Slot Analyzer] 正在调用大模型生成结构化槽位识别报告...")
        report: SlotAnalysisReport = llm_service.generate_structured_output(
            prompt=prompt,
            schema_cls=SlotAnalysisReport,
            temperature=0.1  # 低随机度，保证结构解析稳定
        )

        logger.info(f"[LLM Slot Analyzer] 大模型分析完成！共识别出 {report.total_slots_found} 个待填槽位。")
        logger.info(f"[LLM Slot Analyzer] 总体评估总结: {report.summary}")

        # 详细打印每一个识别出的槽位，日志全量可追踪
        for idx, slot in enumerate(report.slots, 1):
            logger.info(
                f"[槽位 #{idx}] Path='{slot.path}', Label='{slot.label}', "
                f"Intent='{slot.target_field_intent}', 置信度={slot.confidence_score:.2f}, "
                f"推理: {slot.reasoning}"
            )

        return report

    except Exception as e:
        logger.exception(f"[LLM Slot Analyzer] 大模型识别槽位过程发生异常: {str(e)}")
        # 降级防御返回空报告
        return SlotAnalysisReport(
            total_slots_found=0,
            slots=[],
            summary=f"识别失败，产生异常: {str(e)}"
        )
