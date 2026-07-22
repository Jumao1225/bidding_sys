import pytest
from unittest.mock import patch, MagicMock
from app.agents.nodes.cost_agent import cost_node, CostItem, CostAnalysisResult

def test_cost_item_pydantic_schema_validation():
    """测试 CostItem 基础模型的结构化校验，包含星号关键指标与品牌要求"""
    item = CostItem(
        name="核心交换机*",
        spec_requirement="24口千兆",
        qty=2.0,
        key_parameters=["双电源冗余", "吞吐量>100Gbps"],
        brand_requirements="指定华为/华三",
        matched_name="核心交换机",
        matched_brand="华为",
        matched_model="S5735-S24T4X",
        matched_manufacturer="华为技术有限公司",
        ref_price=8500.0,
        subtotal=17000.0,
        match_quality="精准匹配",
        warning=""
    )
    assert item.name == "核心交换机*"
    assert "双电源冗余" in item.key_parameters
    assert item.brand_requirements == "指定华为/华三"
    assert item.matched_brand == "华为"
    assert item.subtotal == 17000.0
    assert item.match_quality == "精准匹配"

def test_cost_item_zero_price_fallback():
    """测试当无匹配价格时自动标记未匹配与零价格"""
    item = CostItem(
        name="未知变压器",
        spec_requirement="1000kVA",
        qty=1.0,
        ref_price=0.0,
        subtotal=0.0,
        match_quality="未匹配",
        warning="未在价格库中找到参考价"
    )
    assert item.ref_price == 0.0
    assert item.subtotal == 0.0
    assert item.match_quality == "未匹配"

@patch("app.agents.nodes.cost_agent.SessionLocal")
@patch("app.agents.nodes.cost_agent.document_crud")
@patch("app.agents.nodes.cost_agent.business_crud")
@patch("app.agents.nodes.cost_agent.rag_service")
@patch("app.agents.nodes.cost_agent.llm_service")
def test_cost_node_execution_should_succeed(
    mock_llm, mock_rag, mock_business_crud, mock_document_crud, mock_session
):
    """测试 cost_node 全流程模拟执行与结果计算"""
    # 1. Mock DB Session
    mock_db = MagicMock()
    mock_session.return_value = mock_db
    mock_db.query.return_value.filter.return_value.first.return_value = None
    
    # 2. Mock Document
    mock_doc = MagicMock()
    mock_doc.parsed_metadata = {"budget_limit": "200000"}
    mock_document_crud.get_document_by_id.return_value = mock_doc
    
    # 3. Mock Price Reference
    mock_price_ref = MagicMock()
    mock_price_ref.item_name = "核心交换机"
    mock_price_ref.brand = "华为"
    mock_price_ref.spec = "24口"
    mock_price_ref.model = "S5735"
    mock_price_ref.manufacturer = "华为"
    mock_price_ref.unit_price = 8500.0
    mock_price_ref.unit = "台"
    mock_price_ref.remark = "测试"
    mock_business_crud.get_all_price_references.return_value = [mock_price_ref]
    
    # 4. Mock RAG Text
    mock_rag.search_bidding_document.return_value = "采购清单：核心交换机 2台"
    
    # 5. Mock LLM Structured Output
    mock_analysis_result = CostAnalysisResult(
        items=[
            CostItem(
                name="核心交换机",
                spec_requirement="24口千兆",
                qty=2.0,
                unit="台",
                matched_name="核心交换机",
                matched_brand="华为",
                matched_model="S5735",
                matched_manufacturer="华为",
                ref_price=8500.0,
                subtotal=17000.0,
                match_quality="精准匹配",
                warning=""
            )
        ],
        analysis_summary="核算正常"
    )
    mock_llm.generate_structured_output.return_value = mock_analysis_result
    
    # 执行 cost_node
    state = {
        "document_id": "doc-123",
        "user_id": "user-123",
        "tenant_id": "tenant-123"
    }
    
    result = cost_node(state)
    
    assert "cost_analysis" in result
    cost_data = result["cost_analysis"]
    assert cost_data["total_cost"] == 17000.0
    assert cost_data["budget_limit"] == "200000"
    assert "预算可控" in cost_data["budget_status"]
    assert len(cost_data["items"]) == 1
    assert cost_data["items"][0]["matched_brand"] == "华为"
