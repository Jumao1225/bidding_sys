import pytest
import json
import os
from unittest.mock import patch
from app.agents.nodes.strategy_agent import analyze_qualifications_node, identify_risks_node

@pytest.fixture
def mock_data():
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mock_responses.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)

@patch('app.services.llm_service.llm_service.generate_structured_json')
def test_analyze_qualifications_node(mock_generate, mock_data):
    mock_generate.return_value = mock_data["strategy_node_qualifications_response"]
    
    state = {"doc_text": "需要CMMI5资质", "company_quals": "有CMMI5"}
    result = analyze_qualifications_node(state)
    
    mock_generate.assert_called_once()
    assert result["qualifications_analysis"]["match_score"] == 85

@patch('app.services.llm_service.llm_service.generate_structured_json')
def test_identify_risks_node(mock_generate, mock_data):
    mock_generate.return_value = mock_data["strategy_node_risks_response"]
    
    state = {"doc_text": "违约金极高"}
    result = identify_risks_node(state)
    
    mock_generate.assert_called_once()
    assert len(result["risks_analysis"]) == 1
    assert result["risks_analysis"][0]["severity"] == "高"


@patch("app.agents.nodes.strategy_agent.persist_worker_analysis_result")
@patch("app.agents.nodes.strategy_agent.SessionLocal")
@patch("app.agents.tools.writer_tools.get_company_qualifications_tool", return_value=[])
@patch("app.agents.nodes.strategy_agent.rag_service.search_bidding_document", return_value="")
@patch("app.agents.nodes.strategy_agent.document_crud.get_all_metadata", return_value={})
@patch("app.services.llm_service.llm_service.generate_structured_json")
def test_analyze_qualifications_node_should_persist_success_immediately(
    mock_generate,
    mock_metadata,
    mock_rag,
    mock_company_quals,
    mock_session_local,
    mock_persist,
    mock_data,
):
    """履约盘点成功后应在返回总流程前立即保存结果。"""
    mock_generate.return_value = mock_data["strategy_node_qualifications_response"]

    result = analyze_qualifications_node({
        "document_id": "doc-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "doc_text": "需要CMMI5资质",
        "company_quals": "有CMMI5",
    })

    assert result["worker_summaries"][0]["status"] == "success"
    mock_persist.assert_called_once()
    assert mock_persist.call_args.kwargs["worker_name"] == "strategy_qual"
    assert mock_persist.call_args.kwargs["result_updates"]["qualifications_analysis"] == result["qualifications_analysis"]


@patch("app.agents.nodes.strategy_agent.persist_worker_analysis_result")
@patch("app.worker.tasks.emit_agent_log")
@patch("app.agents.nodes.strategy_agent.SessionLocal")
@patch("app.agents.nodes.strategy_agent.rag_service.search_bidding_document", return_value="")
@patch("app.agents.nodes.strategy_agent.document_crud.get_all_metadata", return_value={})
@patch("app.services.llm_service.llm_service.generate_structured_json", side_effect=RuntimeError("Connection error"))
def test_identify_risks_node_connection_error_should_mark_failed_without_empty_result(
    mock_generate,
    mock_metadata,
    mock_rag,
    mock_session_local,
    mock_emit_log,
    mock_persist,
):
    """风险 LLM 连接失败时应返回失败状态，不能返回空数组伪装成无风险。"""
    result = identify_risks_node({
        "document_id": "doc-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    })

    assert "risks_analysis" not in result
    assert result["worker_summaries"][0]["status"] == "failed"
    mock_persist.assert_called_once()
    assert mock_persist.call_args.kwargs["worker_name"] == "strategy_risk"
    assert mock_persist.call_args.kwargs["status"] == "failed"
    assert mock_persist.call_args.kwargs["error_type"] == "llm_connection_error"
