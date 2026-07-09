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
