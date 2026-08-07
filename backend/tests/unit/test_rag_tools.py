"""
RAG 工具单元测试 (tests/unit/test_rag_tools.py)
用于测试整章原文拉取工具 (get_full_chapter_text) 与 RAGService 的完整连贯性。
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.rag_service import rag_service
from app.agents.tools.rag_tools import get_full_chapter_text


def test_get_full_chapter_text_success_should_concat_chunks():
    """测试获取整章原文成功时，按 chunk_index 顺序无错漏拼接所有段落"""
    mock_chunk1 = MagicMock()
    mock_chunk1.section_title = "第三章 合同条款"
    mock_chunk1.chunk_index = 0
    mock_chunk1.content = "第一条：付款条件为预付款30%。"

    mock_chunk2 = MagicMock()
    mock_chunk2.section_title = "第三章 合同条款"
    mock_chunk2.chunk_index = 1
    mock_chunk2.content = "第二条：质保期为2年，故障4小时内响应。"

    mock_query = MagicMock()
    mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_chunk1, mock_chunk2]

    with patch("app.services.rag_service.SessionLocal") as mock_session_cls:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value = mock_query

        res = rag_service.get_full_chapter_text("doc_123", "合同条款")

        assert "第三章 合同条款" in res
        assert "共 2 个段落" in res
        assert "付款条件为预付款30%" in res
        assert "质保期为2年" in res


def test_get_full_chapter_text_empty_should_return_not_found_msg():
    """测试当找不到目标章节时返回清晰提示"""
    mock_query = MagicMock()
    mock_query.filter.return_value.order_by.return_value.all.return_value = []

    with patch("app.services.rag_service.SessionLocal") as mock_session_cls:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value = mock_query

        res = rag_service.get_full_chapter_text("doc_123", "不存在的章节")

        assert "未能在文档中检索到章节名称匹配" in res


def test_get_full_chapter_text_tool_denied():
    """测试工具无权限拦截逻辑"""
    with patch("app.agents.tools.security.validate_document_access", return_value=False):
        res = get_full_chapter_text.invoke({"document_id": "doc_456", "chapter_name": "合同条款"})
        assert "拒绝访问" in res
