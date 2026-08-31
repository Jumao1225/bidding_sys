"""
工程元数据多表格并发提取与聚合单元测试 (test_engineering_service_chunked.py)
"""

import re
import pytest
from unittest.mock import patch, MagicMock
from app.services.metadata.engineering_service import (
    EngineeringService,
    EngineeringSchema,
    EquipmentItem,
    _build_semantic_engineering_chunks,
)

@patch("app.services.metadata.engineering_service.llm_service")
def test_engineering_service_sends_table_scoped_context_in_separate_calls(mock_llm):
    """测试多个表格未超出上下文上限时，EngineeringService 整体提交并汇总结果"""
    # 模拟返回的子 Schema
    sub_schema_1 = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="10kV开关柜", quantity=2.0, unit="面", specifications="12kV 630A", section_name="10kV高压开关柜区域", section_evidence="10kV高压开关柜区域"),
            EquipmentItem(item_name="真空断路器", parent_item="10kV开关柜", per_set_quantity=1.0, quantity=2.0, unit="台", specifications="12kV 630A 25kA", section_name="10kV高压开关柜区域", section_evidence="10kV高压开关柜区域")
        ],
        special_working_conditions=["带电施工"],
        mandatory_standards=["GB 50059"]
    )
    
    sub_schema_2 = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="2000kVA光伏升压箱变", quantity=4.0, unit="套", specifications="2000kVA 10kV", section_name="升压箱变区域", section_evidence="升压箱变区域"),
            EquipmentItem(item_name="10kV变压器", parent_item="2000kVA光伏升压箱变", per_set_quantity=1.0, quantity=4.0, unit="台", specifications="2000kVA", section_name="升压箱变区域", section_evidence="升压箱变区域")
        ],
        special_working_conditions=["水上作业"],
        mandatory_standards=["GB 50052"]
    )
    
    mock_llm.generate_structured_output.return_value = EngineeringSchema(
        main_equipment_list=sub_schema_1.main_equipment_list + sub_schema_2.main_equipment_list,
        special_working_conditions=sub_schema_1.special_working_conditions + sub_schema_2.special_working_conditions,
        mandatory_standards=sub_schema_1.mandatory_standards + sub_schema_2.mandatory_standards,
    )
    
    service = EngineeringService()
    
    multi_table_context = """
    ### 10kV高压开关柜区域
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格</th><th>数量</th><th>单位</th></tr>
        <tr><td>1</td><td>10kV开关柜</td><td>12kV 630A</td><td>2</td><td>面</td></tr>
    </table>
    
    ### 升压箱变区域
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格</th><th>数量</th><th>单位</th></tr>
        <tr><td>1</td><td>2000kVA光伏升压箱变</td><td>2000kVA 10kV</td><td>4</td><td>套</td></tr>
    </table>
    """
    
    def result_for_table(prompt, **_kwargs):
        """根据当前表格内容返回对应的模型结果，避免重复汇总。"""
        if "10kV开关柜" in prompt:
            return sub_schema_1
        return sub_schema_2

    mock_llm.generate_structured_output.side_effect = result_for_table

    with patch.object(service, "_save_to_db") as mock_save:
        result = service.extract_metadata(multi_table_context, document_id="doc-test-123")
        
        assert len(result.main_equipment_list) == 4
        item_names = [it.item_name for it in result.main_equipment_list]
        assert "10kV开关柜" in item_names
        assert "真空断路器" in item_names
        assert "2000kVA光伏升压箱变" in item_names
        assert "10kV变压器" in item_names
        # 模型返回的顶层分项字段应被保留，不应被前端或业务名称映射覆盖。
        assert {item.section_name for item in result.main_equipment_list} == {
            "10kV高压开关柜区域", "升压箱变区域"
        }
        
        # 验证工况与标准去重汇总
        assert "带电施工" in result.special_working_conditions
        assert "水上作业" in result.special_working_conditions
        assert "GB 50059" in result.mandatory_standards
        assert "GB 50052" in result.mandatory_standards
        
        # 验证自动触发落盘
        mock_save.assert_called_once()

        # 聚合请求必须同时包含全部表格上下文与 section_name 字段约束。
        assert mock_llm.generate_structured_output.call_count == 2
        prompts = [call.kwargs["prompt"] for call in mock_llm.generate_structured_output.call_args_list]
        assert all("section_name" in prompt for prompt in prompts)
        assert all("当前工程清单上下文与技术要求" in prompt for prompt in prompts)
        assert any("10kV开关柜" in prompt and "2000kVA光伏升压箱变" not in prompt for prompt in prompts)
        assert any("2000kVA光伏升压箱变" in prompt and "10kV开关柜" not in prompt for prompt in prompts)


def test_engineering_service_splits_oversized_context_by_complete_table_units():
    """测试上下文超限时按完整表格和前置标题拆分，不丢失任何表格内容。"""
    context = """
    ## 区域A
    <table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>
    <tr><td>1</td><td>设备A</td><td>1</td></tr>
    <tr><td>2</td><td>设备A的说明</td><td>2</td></tr></table>

    ## 区域B
    <table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>
    <tr><td>1</td><td>设备B</td><td>3</td></tr>
    <tr><td>2</td><td>设备B的说明</td><td>4</td></tr></table>
    """
    matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, sections = _build_semantic_engineering_chunks(context, matches, max_chars=220)

    assert len(chunks) == 2
    assert len(chunks) == len(sections)
    merged = "\n".join(chunks)
    for marker in ["区域A", "设备A的说明", "区域B", "设备B的说明"]:
        assert marker in merged


def test_engineering_service_splits_high_row_context_before_model_output_overflow(monkeypatch):
    """原文字符数未超限但数据行过多时，也应按完整表格拆分，避免结构化输出截断。"""
    monkeypatch.setenv("ENGINEERING_MAX_SOURCE_ROWS_PER_CONTEXT", "10")
    context = """
    ## 区域A
    <table><tr><th>序号</th><th>名称</th><th>数量</th></tr>
    <tr><td>1</td><td>设备A</td><td>1</td></tr>
    <tr><td>2</td><td>设备B</td><td>2</td></tr>
    <tr><td>3</td><td>设备E</td><td>3</td></tr>
    <tr><td>4</td><td>设备F</td><td>4</td></tr>
    <tr><td>5</td><td>设备G</td><td>5</td></tr>
    <tr><td>6</td><td>设备H</td><td>6</td></tr></table>

    ## 区域B
    <table><tr><th>序号</th><th>名称</th><th>数量</th></tr>
    <tr><td>1</td><td>设备C</td><td>1</td></tr>
    <tr><td>2</td><td>设备D</td><td>2</td></tr>
    <tr><td>3</td><td>设备I</td><td>3</td></tr>
    <tr><td>4</td><td>设备J</td><td>4</td></tr>
    <tr><td>5</td><td>设备K</td><td>5</td></tr>
    <tr><td>6</td><td>设备L</td><td>6</td></tr></table>
    """
    matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, sections = _build_semantic_engineering_chunks(context, matches, max_chars=10000)

    assert len(chunks) == 2
    assert len(chunks) == len(sections)
    assert all("<th>序号</th>" in chunk for chunk in chunks)
    assert all(marker in chunks[0] for marker in ["设备A", "设备B", "设备E", "设备F", "设备G", "设备H"])
    assert all(marker in chunks[1] for marker in ["设备C", "设备D", "设备I", "设备J", "设备K", "设备L"])


def test_engineering_service_splits_large_table_with_local_context_attached():
    """测试超长表格按完整行拆分时，每个子块都保留表头和表格前局部上下文。"""
    context = """
    ## 某分区
    该分区清单说明：以下表格中的父级和子级关系必须结合原文判断。
    <table><tr><th>序号</th><th>名称</th><th>规格</th><th>数量</th></tr>
    <tr><td>1</td><td>设备A</td><td>长规格说明A</td><td>1</td></tr>
    <tr><td>2</td><td>设备B</td><td>长规格说明B</td><td>2</td></tr>
    <tr><td>3</td><td>设备C</td><td>长规格说明C</td><td>3</td></tr></table>
    """
    matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, sections = _build_semantic_engineering_chunks(context, matches, max_chars=150)

    assert len(chunks) >= 2
    assert len(chunks) == len(sections)
    assert all("## 某分区" in chunk for chunk in chunks)
    assert all("该分区清单说明" in chunk for chunk in chunks)
    assert all("<th>序号</th>" in chunk for chunk in chunks)
    merged = "\n".join(chunks)
    for marker in ["设备A", "设备B", "设备C"]:
        assert marker in merged
