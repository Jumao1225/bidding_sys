"""
单元测试：大模型槽位识别分析器 (test_llm_slot_analyzer.py)
"""

import pytest
from unittest.mock import patch, MagicMock
from app.services.llm_slot_analyzer import (
    analyze_slots_with_llm,
    SlotAnalysisReport,
    SlotItem,
)


def test_analyze_slots_with_empty_input():
    """测试当文档结构为空时的防御逻辑"""
    report = analyze_slots_with_llm("")
    assert report.total_slots_found == 0
    assert len(report.slots) == 0


@patch("app.services.llm_service.llm_service.generate_structured_output")
def test_analyze_slots_with_mock_llm(mock_generate):
    """测试大模型成功分析并输出结构化槽位报告"""
    mock_report = SlotAnalysisReport(
        total_slots_found=2,
        slots=[
            SlotItem(
                path="/body/p[1]",
                run_index=1,
                label="投标人名称：",
                raw_placeholder="______",
                target_field_intent="company_name",
                confidence_score=0.98,
                reasoning="明确的投标人名称下划线填空"
            ),
            SlotItem(
                path="/body/p[2]",
                run_index=0,
                label="统一社会信用代码：",
                raw_placeholder="【 】",
                target_field_intent="credit_code",
                confidence_score=0.95,
                reasoning="信用代码括号占位符"
            )
        ],
        summary="识别出 2 个核心要素槽位"
    )
    mock_generate.return_value = mock_report

    sample_doc_str = "/body/p[1]: 投标人名称：______\n/body/p[2]: 统一社会信用代码：【 】"
    report = analyze_slots_with_llm(sample_doc_str)

    assert report.total_slots_found == 2
    assert report.slots[0].target_field_intent == "company_name"
    assert report.slots[1].target_field_intent == "credit_code"
    assert report.slots[0].path == "/body/p[1]"
