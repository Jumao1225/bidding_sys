"""
人工切片与章节标注 (Human Annotation Workflow) 单元测试

遵照测试规范：
1. 命名规范：test_<功能>_<场景>_<期望结果>
2. 覆盖正常情况、异常情况与边界情况
"""

import pytest
from unittest.mock import MagicMock, patch

from app.schemas.bid_scorer_schema import ChunkUpdateItem
from app.services.bid_scorer_service import bid_scorer_service
from app.db.models.project import Document, DocChunk


def test_get_document_chunks_normal_should_return_sorted_chunks():
    """正常情况：获取指定文档的切片列表，按 chunk_index 排序返回"""
    mock_db = MagicMock()
    mock_doc = Document(id="doc_123", user_id="u_001", tenant_id="t_001")
    mock_chunks = [
        DocChunk(id="c1", document_id="doc_123", chunk_index=0, section_title="一、投标函", content="内容1"),
        DocChunk(id="c2", document_id="doc_123", chunk_index=1, section_title="二、技术方案", content="内容2"),
    ]

    mock_db.query.return_value.filter.return_value.first.return_value = mock_doc
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_chunks

    result = bid_scorer_service.get_document_chunks_for_annotation(
        db=mock_db,
        document_id="doc_123",
        user_id="u_001",
        tenant_id="t_001",
    )

    assert len(result) == 2
    assert result[0].section_title == "一、投标函"
    assert result[1].section_title == "二、技术方案"


def test_get_document_chunks_not_found_should_raise_error():
    """异常情况：文档不存在或无权限时，应该抛出 ValueError 异常"""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="文档未找到或无访问权限"):
        bid_scorer_service.get_document_chunks_for_annotation(
            db=mock_db,
            document_id="non_exist_doc",
            user_id="u_001",
            tenant_id="t_001",
        )


@patch("app.services.bid_scorer_service.llm_service")
def test_save_human_annotated_chunks_normal_should_update_db_and_embeddings(mock_llm_service):
    """正常情况：保存人工标注切片，应自动计算向量并更新文档 parsed_metadata"""
    mock_db = MagicMock()
    mock_doc = Document(id="doc_123", user_id="u_001", tenant_id="t_001", parsed_metadata={})
    mock_db.query.return_value.filter.return_value.first.return_value = mock_doc

    mock_llm_service.generate_embeddings.return_value = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    updates = [
        ChunkUpdateItem(chunk_index=0, section_title="一、商务部分", content="修改后的商务内容", page_num=1),
        ChunkUpdateItem(chunk_index=1, section_title="二、技术方案说明", content="修改后的技术内容", page_num=10),
    ]

    res = bid_scorer_service.save_human_annotated_chunks(
        db=mock_db,
        document_id="doc_123",
        chunk_updates=updates,
        user_id="u_001",
        tenant_id="t_001",
    )

    assert res["document_id"] == "doc_123"
    assert res["chunk_count"] == 2
    assert res["human_annotated"] is True
    assert mock_doc.parsed_metadata["human_annotated"] is True
    assert mock_doc.parsed_metadata["chunk_count"] == 2
    mock_db.commit.assert_called_once()
