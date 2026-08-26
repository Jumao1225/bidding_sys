from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from app.agents.tools.metadata_tools import (
    _build_financial_core_context,
    _select_financial_core_chunks,
)


def _build_chunk(index: int, content: str) -> SimpleNamespace:
    """构造仅包含财务上下文筛选所需属性的文档分块。"""
    return SimpleNamespace(chunk_index=index, content=content)


def test_select_financial_core_chunks_should_keep_budget_and_max_limit_evidence():
    """同时存在采购预算与最高投标限价时，应保留两类原文证据。"""
    chunks = [
        _build_chunk(1, "第一章 项目概况"),
        _build_chunk(2, "本项目采购总预算为人民币 3600000 元。"),
        _build_chunk(3, "投标报价不得超过最高投标限价人民币 3200000 元。"),
        _build_chunk(4, "其他商务条款"),
    ]

    selected_chunks = _select_financial_core_chunks(chunks)
    selected_content = "\n".join(chunk.content for chunk in selected_chunks)

    assert "采购总预算" in selected_content
    assert "最高投标限价" in selected_content


def test_select_financial_core_chunks_should_support_common_aliases():
    """金额字段使用常见别名时，仍应纳入定向上下文。"""
    chunks = [
        _build_chunk(1, "项目预算金额为人民币 150 万元。"),
        _build_chunk(2, "本项目招标控制价为人民币 140 万元。"),
    ]

    selected_chunks = _select_financial_core_chunks(chunks)
    selected_content = "\n".join(chunk.content for chunk in selected_chunks)

    assert "预算金额" in selected_content
    assert "招标控制价" in selected_content


def test_select_financial_core_chunks_should_return_empty_for_empty_document():
    """文档无分块时应安全返回空列表，交由通用检索继续处理。"""
    assert _select_financial_core_chunks([]) == []


@patch("app.db.session.SessionLocal")
def test_build_financial_core_context_should_fallback_when_database_query_fails(mock_session_local):
    """定向上下文读取异常时，应返回空串并让后续通用 RAG 继续执行。"""
    mock_session = MagicMock()
    mock_session.query.side_effect = OperationalError("SELECT", {}, RuntimeError("数据库不可用"))
    mock_session_local.return_value = mock_session

    context = _build_financial_core_context("document-test", "tenant-test")

    assert context == ""
    mock_session.close.assert_called_once()
