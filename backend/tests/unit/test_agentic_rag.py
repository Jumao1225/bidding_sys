# -*- coding: utf-8 -*-
import pytest
from app.agents.tools.bid_scorer_tools import (
    extract_missing_keywords_from_round,
    active_refine_context_with_keywords,
)

def test_extract_missing_keywords_from_deduction_reasons():
    mock_r1_result = [
        {
            "item_code": "ITEM_01",
            "ai_score": 3.0,
            "max_score": 7.0,
            "deduction_reason": "只提供了现场操作培训，缺少日常运行管理培训和维保实操培训，判定部分缺失。",
            "suggestion": "建议补充日常运行管理培训内容与施工工艺流程。",
        },
        {
            "item_code": "ITEM_02",
            "ai_score": 10.0,
            "max_score": 10.0,
            "deduction_reason": "满足全部要求，无扣分。",
            "suggestion": "继续保持。",
        }
    ]

    kws = extract_missing_keywords_from_round(mock_r1_result)
    assert any("日常运行管理" in kw for kw in kws)
    assert any("维保实操" in kw for kw in kws) or any("施工工艺" in kw for kw in kws)

def test_active_refine_context_with_empty_keywords():
    original_text = "这是原始投标文件上下文内容。"
    refined = active_refine_context_with_keywords(
        document_id="",
        bid_content=original_text,
        missing_keywords=[],
    )
    assert refined == original_text
