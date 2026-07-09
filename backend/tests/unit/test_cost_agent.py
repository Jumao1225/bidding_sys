import pytest
import json
import os
from unittest.mock import patch
from app.agents.nodes.cost_agent import cost_node

@pytest.fixture
def mock_data():
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mock_responses.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)

@patch('app.services.llm_service.llm_service.generate_structured_json')
def test_cost_node(mock_generate, mock_data):
    mock_generate.return_value = mock_data["cost_node_response"]
    
    state = {"doc_text": "需要采购2台服务器。"}
    result = cost_node(state)
    
    mock_generate.assert_called_once()
    assert result["cost_analysis"]["total_cost"] == 90000
    assert len(result["cost_analysis"]["items"]) == 1
    assert result["cost_analysis"]["items"][0]["matched_name"] == "高性能服务器"
