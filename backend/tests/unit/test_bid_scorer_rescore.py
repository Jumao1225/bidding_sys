"""
单元测试：标书打分交互式微调重算逻辑 (test_bid_scorer_rescore.py)
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.bid_scorer_service import bid_scorer_service


def test_build_scoring_prompt_with_user_instruction():
    """测试 Prompt 构造中成功注入用户微调规则"""
    from app.agents.tools.bid_scorer_tools import _build_scoring_prompt

    items = [{"title": "价格分", "max_score": 30.0, "scoring_criteria": "低价优先"}]
    user_instruction = "单标书评估，默认其投标总价为有效最低价，按满分30分计算"

    prompt = _build_scoring_prompt(
        items=items,
        bid_content="投标总价 100万元",
        round_idx=0,
        category="价格分",
        user_instruction=user_instruction,
    )

    assert "最高优先级指令：用户微调评审规则" in prompt
    assert "单标书评估，默认其投标总价为有效最低价" in prompt


@patch("app.agents.tools.bid_scorer_tools.llm_service.generate_text")
@patch("app.agents.tools.bid_scorer_tools.rag_service.search_bidding_document")
def test_rescore_category_service_flow(mock_rag, mock_llm):
    """测试微调重算服务流程"""
    mock_rag.return_value = "## 投标报价表\n总价：1072658.46元"
    mock_llm.return_value = """[
        {
            "item_code": "ITEM_PRICE",
            "ai_score": 30.0,
            "confidence": 1.0,
            "scoring_basis": "根据评委指令，单标书默认最低报价，给予满分「1072658.46元」",
            "deduction_reason": null,
            "suggestion": null
        }
    ]"""

    db = MagicMock()

    # Mock BidScoreResult
    mock_result = MagicMock()
    mock_result.id = "res_123"
    mock_result.document_id = "doc_123"
    mock_result.source_doc_id = "src_123"
    mock_result.max_possible = 100.0
    mock_result.category_scores = {"价格分": {"score": 0.0, "max_total": 30.0, "count": 1}}

    # Mock EvaluationMetadata
    mock_meta = MagicMock()
    mock_meta.score_tree = [
        {"item_code": "ITEM_PRICE", "category": "价格分", "title": "价格分", "max_score": 30.0}
    ]

    # Mock BidScoreItem
    mock_item = MagicMock()
    mock_item.category = "价格分"
    mock_item.item_code = "ITEM_PRICE"
    mock_item.title = "价格分"
    mock_item.max_score = 30.0
    mock_item.ai_score = 0.0

    from app.db.models.bid_score import BidScoreResult, BidScoreItem
    from app.db.models.metadata import EvaluationMetadata

    def query_side_effect(model):
        q_mock = MagicMock()
        if model == BidScoreResult:
            q_mock.filter.return_value.first.return_value = mock_result
        elif model == EvaluationMetadata:
            q_mock.filter.return_value.first.return_value = mock_meta
        elif model == BidScoreItem:
            q_mock.filter.return_value.first.return_value = mock_item
            q_mock.filter.return_value.all.return_value = [mock_item]
        return q_mock

    db.query.side_effect = query_side_effect

    res = bid_scorer_service.rescore_category_with_instruction(
        db=db,
        result_id="res_123",
        category="价格分",
        user_instruction="单标书默认按满分计算",
        tenant_id="tenant_default",
        scoring_rounds=1,
    )

    assert res is not None
    assert mock_item.ai_score == 30.0
    assert mock_result.total_score == 30.0
    assert mock_rag.call_args.kwargs["tenant_id"] == "tenant_default"
    assert mock_llm.call_args.kwargs["tenant_id"] == "tenant_default"


def test_validate_scoring_documents_wrong_tenant_should_raise_error():
    """异常场景：投标文档不属于当前租户时，启动评分前应拒绝访问。"""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_db
    with patch("app.db.session.SessionLocal", return_value=mock_session):
        with pytest.raises(ValueError, match="投标文件不存在或无权访问"):
            bid_scorer_service._validate_scoring_documents(
                document_id="bid_other_tenant",
                source_doc_id="source_001",
                user_id="user_001",
                tenant_id="tenant_current",
            )


def test_validate_scoring_documents_without_chunks_should_raise_error():
    """边界场景：租户和评分大纲合法但没有切片时，应拒绝启动评分。"""
    mock_db = MagicMock()
    mock_bid_document = MagicMock()
    mock_source_document = MagicMock()
    mock_eval_meta = MagicMock(score_tree=[{"category": "技术分"}])

    query_results = [
        mock_bid_document,
        mock_source_document,
        mock_eval_meta,
    ]

    def query_side_effect(model):
        query = MagicMock()
        if query_results:
            query.filter.return_value.first.return_value = query_results.pop(0)
        else:
            query.filter.return_value.count.return_value = 0
        return query

    mock_db.query.side_effect = query_side_effect

    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_db
    with patch("app.db.session.SessionLocal", return_value=mock_session):
        with pytest.raises(ValueError, match="尚未完成向量化解析"):
            bid_scorer_service._validate_scoring_documents(
                document_id="bid_001",
                source_doc_id="source_001",
                user_id="user_001",
                tenant_id="tenant_current",
            )
