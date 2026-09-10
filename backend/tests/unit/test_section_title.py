"""章节标题兼容工具的单元测试。"""

from unittest.mock import MagicMock, patch

from app.services.rag_service import (
    _has_substantive_section_chunks,
    rag_service,
    _select_source_chapters,
)
from app.utils.section_title import section_title_stem


def test_section_title_stem_should_match_numbering_variants():
    """不同编号格式只影响前缀，标题正文应得到同一兼容键。"""
    assert section_title_stem("第一章 节点甲") == section_title_stem("（一）节点甲")


def test_select_source_chapters_should_match_legacy_numbering():
    """原文章节应兼容历史分块使用的括号序号。"""
    chapters = [
        {
            "title": "第一章 节点甲",
            "section_path": "第一章 节点甲",
            "text": "节点甲正文",
        },
        {
            "title": "第二章 节点乙",
            "section_path": "第二章 节点乙",
            "text": "节点乙正文",
        },
    ]

    result = _select_source_chapters(chapters, "（一）节点甲")

    assert result == [chapters[0]]


def test_has_substantive_section_chunks_should_distinguish_heading_only_chunk():
    """只有章节标题的历史分块应触发原文回源，正文分块则不应触发。"""
    heading_only = type(
        "Chunk",
        (),
        {"section_title": "第一章 节点甲", "content": "第一章 节点甲"},
    )()
    substantive = type(
        "Chunk",
        (),
        {"section_title": "第一章 节点甲", "content": "第一章 节点甲\n节点甲正文"},
    )()

    assert _has_substantive_section_chunks([heading_only]) is False
    assert _has_substantive_section_chunks([substantive]) is True


def test_get_full_chapter_text_should_fallback_to_source_for_heading_only_chunk():
    """历史数据库只保留章节标题时，应返回解析原文中的完整章节。"""
    title_query = MagicMock()
    title_query.filter.return_value.distinct.return_value.all.return_value = [
        ("（一）节点甲",),
    ]
    chunk_query = MagicMock()
    heading_only = MagicMock()
    heading_only.section_title = "（一）节点甲"
    heading_only.content = "（一）节点甲"
    heading_only.chunk_index = 1
    chunk_query.filter.return_value.order_by.return_value.all.return_value = [heading_only]

    source_chapters = [
        {
            "title": "第一章 节点甲",
            "section_path": "第一章 节点甲",
            "text": "第一章 节点甲\n节点甲正文",
        }
    ]

    with patch("app.services.rag_service.SessionLocal") as session_cls:
        mock_db = MagicMock()
        session_cls.return_value = mock_db
        mock_db.query.side_effect = [title_query, chunk_query]
        with patch.object(rag_service, "_load_source_chapters", return_value=source_chapters):
            result = rag_service.get_full_chapter_text("doc_123", "第一章 节点甲")

    assert "来源：解析原文" in result
    assert "节点甲正文" in result
