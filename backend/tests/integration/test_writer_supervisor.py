import pytest
import json
from unittest.mock import patch, MagicMock

from app.agents.tools.writer_supervisor_tools import (
    analyze_bid_format_chapter,
    spawn_chapter_agent,
    review_and_assemble,
    FormatAnalysisResult,
    ChapterClassification,
)
from app.agents.tools.chapter_agent_tools import (
    clear_document_chapter_results,
    write_chapter_content,
)


def test_analyze_bid_format_chapter_mocked_llm():
    """测试 analyze_bid_format_chapter 工具提取并分类章节列表"""
    doc_id = "test_doc_sup"
    format_text = """
    # 第六章 投标文件格式
    
    一、投标函
    致：________
    
    二、开标一览表
    | 序号 | 项目 | 金额 |
    
    三、技术方案
    请详细阐述技术选型与施工组织。
    """

    mock_result = FormatAnalysisResult(
        source_chapter="投标文件格式",
        total_chapters=3,
        chapters=[
            ChapterClassification(
                chapter_number="一",
                chapter_title="一、投标函",
                category="needs_fill",
                category_reason="有致：下划线",
                mapping_hint="bid_letter",
                template_text="致：________"
            ),
            ChapterClassification(
                chapter_number="二",
                chapter_title="二、开标一览表",
                category="needs_data",
                category_reason="有空白表格",
                mapping_hint="pricing"
            ),
            ChapterClassification(
                chapter_number="三",
                chapter_title="三、技术方案",
                category="needs_writing",
                category_reason="只有标题和说明",
                mapping_hint="technical"
            )
        ]
    )

    with patch("app.services.llm_service.llm_service.generate_structured_output", return_value=mock_result):
        res = analyze_bid_format_chapter.invoke({
            "document_id": doc_id,
            "format_chapter_text": format_text
        })

        assert "共识别 3 个章节" in res
        assert "needs_fill" in res
        assert "needs_data" in res
        assert "needs_writing" in res


    clear_document_chapter_results(doc_id)


def test_spawn_batch_chapter_agents_execution():
    """测试 spawn_batch_chapter_agents 批量并发派发工具"""
    from app.agents.tools.writer_supervisor_tools import spawn_batch_chapter_agents
    doc_id = "test_doc_batch"
    clear_document_chapter_results(doc_id)

    batch_input = [
        {
            "chapter_title": "五、施工组织设计",
            "chapter_number": "五",
            "mapping_hint": "technical",
            "category": "needs_writing",
            "content_hint": "施工步骤与技术交底"
        },
        {
            "chapter_title": "六、售后服务承诺",
            "chapter_number": "六",
            "mapping_hint": "service",
            "category": "needs_writing",
            "content_hint": "响应时间说明"
        }
    ]

    clear_document_chapter_results(doc_id)


def test_spawn_batch_chapter_agents_auto_fallback():
    """测试 spawn_batch_chapter_agents 传入 'auto' 或损坏 JSON 时的缓存降级能力"""
    from app.agents.tools.writer_supervisor_tools import (
        spawn_batch_chapter_agents,
        _CHAPTER_ANALYSIS_CACHE,
        FormatAnalysisResult,
        ChapterClassification
    )
    doc_id = "test_doc_auto"
    clear_document_chapter_results(doc_id)

    _CHAPTER_ANALYSIS_CACHE[doc_id] = FormatAnalysisResult(
        source_chapter="格式",
        total_chapters=1,
        chapters=[
            ChapterClassification(
                chapter_number="一",
                chapter_title="一、投标函",
                category="needs_fill",
                category_reason="有致：",
                mapping_hint="bid_letter"
            )
        ]
    )

    # 1. 传入 "auto"
    res_auto = spawn_batch_chapter_agents.invoke({
        "document_id": doc_id,
        "chapters_data": "auto"
    })
    data_auto = json.loads(res_auto)
    assert data_auto["status"] == "success"
    assert data_auto["total_dispatched"] == 1

    # 2. 传入损坏的 JSON 字符串
    res_bad = spawn_batch_chapter_agents.invoke({
        "document_id": doc_id,
        "chapters_data": "{bad_json: invalid"
    })
    data_bad = json.loads(res_bad)
    assert data_bad["status"] == "success"
    assert data_bad["total_dispatched"] == 1

    clear_document_chapter_results(doc_id)
    if doc_id in _CHAPTER_ANALYSIS_CACHE:
        del _CHAPTER_ANALYSIS_CACHE[doc_id]


