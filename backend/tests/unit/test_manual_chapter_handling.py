"""needs_writing 人工待办与自动质检隔离测试。"""

from app.agents.bid_filler_agent import (
    _is_manual_chapter_context,
    _normalize_manual_chapters,
)
from app.schemas.bid_filler_schema import BidFillAuditReport


def test_normalize_manual_chapters_should_keep_requirements_and_deduplicate() -> None:
    """正常章节应转为人工待办并保留原始说明，重复章节只保留一条。"""
    chapters = _normalize_manual_chapters([
        {
            "chapter_number": "八",
            "chapter_title": "技术方案",
            "template_text": "请编制完整技术方案",
            "content_hint": "结合项目实际情况说明实施组织",
        },
        {
            "chapter_number": "八",
            "chapter_title": "技术方案",
            "content_hint": "重复结果",
        },
        {"chapter_title": ""},
        "invalid-chapter",
    ])

    assert len(chapters) == 1
    assert chapters[0]["status"] == "manual_pending"
    assert chapters[0]["agent_action"] == "仅提取要求，不修改正文"
    assert chapters[0]["content_hint"] == "结合项目实际情况说明实施组织"


def test_manual_chapter_context_should_match_heading_and_not_match_other_heading() -> None:
    """人工章节标题命中时应隔离质检，其他章节不得被误隔离。"""
    manual_chapters = _normalize_manual_chapters([{"chapter_title": "技术方案"}])

    assert _is_manual_chapter_context("Heading 8 技术方案", manual_chapters) is True
    assert _is_manual_chapter_context("Heading 7 报价表", manual_chapters) is False
    assert _is_manual_chapter_context("", manual_chapters) is False


def test_bid_fill_audit_report_should_expose_manual_pending_count() -> None:
    """审计报告应允许前端直接展示人工待办数量。"""
    report = BidFillAuditReport(
        document_id="document-1",
        manual_chapters=_normalize_manual_chapters([{"chapter_title": "技术方案"}]),
        manual_pending_count=1,
    )

    assert report.manual_pending_count == 1
    assert report.manual_chapters[0].chapter_title == "技术方案"
