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


def test_select_target_qualification_chapters_empty_outline_should_return_empty():
    """空大纲目录边界场景应返回空列表。"""
    from app.agents.nodes.strategy_agent import select_target_qualification_chapters
    assert select_target_qualification_chapters([]) == []


@patch("app.services.llm_service.llm_service.generate_structured_json")
def test_select_target_qualification_chapters_llm_success_should_return_matched(mock_llm):
    """LLM 正常决策时应正确匹配并返回选定章节。"""
    from app.agents.nodes.strategy_agent import select_target_qualification_chapters
    mock_llm.return_value = {
        "selected_chapters": ["第一章 招标公告", "第二章 投标须知"]
    }
    outline = [
        "第一章 招标公告",
        "第二章 投标须知",
        "第三章 采购需求",
        "第四章 合同范本",
    ]
    result = select_target_qualification_chapters(outline, tenant_id="tenant-1")
    assert result == ["第一章 招标公告", "第二章 投标须知"]


@patch("app.services.llm_service.llm_service.generate_structured_json", side_effect=RuntimeError("LLM 502 Bad Gateway"))
def test_select_target_qualification_chapters_llm_error_should_fallback_to_rule_engine(mock_llm):
    """LLM 调用报错时应无缝由关键词规则引擎接管兜底。"""
    from app.agents.nodes.strategy_agent import select_target_qualification_chapters
    outline = [
        "第一章 招标公告",
        "第二章 投标人须知前附表",
        "第三章 评标办法及评分标准",
        "第四章 技术规格清单",
        "第五章 投标格式范本",
    ]
    result = select_target_qualification_chapters(outline, tenant_id="tenant-1")
    # 规则引擎命中包含 公告/须知/前附表/评标/评分 的章节
    assert "第一章 招标公告" in result
    assert "第二章 投标人须知前附表" in result
    assert "第三章 评标办法及评分标准" in result
    assert "第四章 技术规格清单" not in result


@patch("app.agents.nodes.strategy_agent.persist_worker_analysis_result")
@patch("app.agents.nodes.strategy_agent.SessionLocal")
@patch("app.agents.tools.writer_tools.get_company_qualifications_tool", return_value=[])
@patch("app.agents.tools.bid_scorer_tools.get_bid_document_outline", return_value=["第一章 招标公告", "第二章 投标须知"])
@patch("app.agents.nodes.strategy_agent.rag_service.search_bidding_document", return_value="定向原文")
@patch("app.agents.nodes.strategy_agent.document_crud.get_all_metadata", return_value={})
@patch("app.services.llm_service.llm_service.generate_structured_json")
def test_analyze_qualifications_node_should_trigger_fourth_level_fallback_on_llm_error(
    mock_generate,
    mock_metadata,
    mock_rag,
    mock_outline,
    mock_company_quals,
    mock_session_local,
    mock_persist,
):
    """当带长原文深度比对发生 502/断连时，应触发第四级轻量降级兜底比对成功产出结果。"""
    # 第一次选章调用返回选章结果；第二次带原文深度比对抛出 502 异常；第三次降级轻量比对返回成功
    mock_generate.side_effect = [
        {"selected_chapters": ["第一章 招标公告"]},
        RuntimeError("502 Bad Gateway"),
        {
            "match_score": 80,
            "items": [{"requirement": "企业资质", "status": "可以做到", "reason": "具备相应证书"}]
        }
    ]

    result = analyze_qualifications_node({
        "document_id": "doc-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "doc_text": "需要企业资质",
        "company_quals": "具备资质证书",
    })

    assert result["worker_summaries"][0]["status"] == "success"
    assert result["qualifications_analysis"]["match_score"] == 80
    assert len(result["qualifications_analysis"]["items"]) == 1
    mock_persist.assert_called_once()
    assert mock_persist.call_args.kwargs["worker_name"] == "strategy_qual"



