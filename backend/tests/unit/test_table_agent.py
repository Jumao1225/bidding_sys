"""
单元测试：TableAgent 表格智能识别与动态列语义映射 (test_table_agent.py)
"""

import pytest
from unittest.mock import MagicMock, patch
from app.agents.nodes.table_agent import (
    analyze_table_structure_and_map,
    TableMappingDecision,
    ColumnMapping,
    _TABLE_DECISION_CACHE
)


def test_analyze_table_structure_and_map_empty_headers_returns_unknown():
    """测试空表头情况返回 unknown 决策"""
    decision = analyze_table_structure_and_map([], "五、投标配置及分项报价表")
    assert decision.table_type == "unknown"
    assert len(decision.column_mappings) == 0


def test_analyze_table_structure_and_map_mocked_llm():
    """测试常规表头通过 LLM 识别并正确生成 TableMappingDecision"""
    mock_decision = TableMappingDecision(
        table_type="pricing_bom",
        table_reason="表头包含名称、规格、数量、单价、总价等报价关键字",
        column_mappings=[
            ColumnMapping(col_index=0, header_name="序号", field_key="seq"),
            ColumnMapping(col_index=1, header_name="标的物名称", field_key="name"),
            ColumnMapping(col_index=2, header_name="规格型号", field_key="spec"),
            ColumnMapping(col_index=3, header_name="单位", field_key="unit"),
            ColumnMapping(col_index=4, header_name="数量", field_key="qty"),
            ColumnMapping(col_index=5, header_name="单价", field_key="price"),
            ColumnMapping(col_index=6, header_name="总价", field_key="subtotal")
        ]
    )

    _TABLE_DECISION_CACHE.clear()

    with patch("app.agents.nodes.table_agent.llm_service.generate_structured_output", return_value=mock_decision) as mock_llm:
        headers = ["序号", "标的物名称", "规格型号", "单位", "数量", "单价", "总价"]
        res = analyze_table_structure_and_map(headers, "五、投标配置及分项报价表")

        assert res.table_type == "pricing_bom"
        assert len(res.column_mappings) == 7
        assert res.column_mappings[1].field_key == "name"
        assert res.column_mappings[5].field_key == "price"
        mock_llm.assert_called_once()


def test_analyze_table_structure_and_map_memory_cache():
    """测试相同表头与章节二次调用极速命中内存缓存"""
    _TABLE_DECISION_CACHE.clear()

    mock_decision = TableMappingDecision(
        table_type="pricing_bom",
        table_reason="测试缓存",
        column_mappings=[
            ColumnMapping(col_index=0, header_name="序号", field_key="seq")
        ]
    )

    with patch("app.agents.nodes.table_agent.llm_service.generate_structured_output", return_value=mock_decision) as mock_llm:
        headers = ["序号", "标的物名称"]
        section = "五、投标配置及分项报价表"

        res1 = analyze_table_structure_and_map(headers, section)
        res2 = analyze_table_structure_and_map(headers, section)

        assert res1.table_type == "pricing_bom"
        assert res2.table_type == "pricing_bom"
        # 验证 LLM 仅被调用一次，第二次成功命中缓存
        assert mock_llm.call_count == 1
