"""
工程元数据多表格并发提取与聚合单元测试 (test_engineering_service_chunked.py)
"""

import pytest
from unittest.mock import patch, MagicMock
from app.services.metadata.engineering_service import EngineeringService, EngineeringSchema, EquipmentItem

@patch("app.services.metadata.engineering_service.llm_service")
def test_engineering_service_extracts_multi_table_chunks_concurrently(mock_llm):
    """测试当文档包含多个大型标的物表格时，EngineeringService 自动按表格分块并发提取并汇总合并"""
    # 模拟返回的子 Schema
    sub_schema_1 = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="10kV开关柜", quantity=2.0, unit="面", specifications="12kV 630A"),
            EquipmentItem(item_name="真空断路器", parent_item="10kV开关柜", per_set_quantity=1.0, quantity=2.0, unit="台", specifications="12kV 630A 25kA")
        ],
        special_working_conditions=["带电施工"],
        mandatory_standards=["GB 50059"]
    )
    
    sub_schema_2 = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="2000kVA光伏升压箱变", quantity=4.0, unit="套", specifications="2000kVA 10kV"),
            EquipmentItem(item_name="10kV变压器", parent_item="2000kVA光伏升压箱变", per_set_quantity=1.0, quantity=4.0, unit="台", specifications="2000kVA")
        ],
        special_working_conditions=["水上作业"],
        mandatory_standards=["GB 50052"]
    )
    
    mock_llm.generate_structured_output.side_effect = [sub_schema_1, sub_schema_2]
    
    service = EngineeringService()
    
    multi_table_context = """
    ### 一、10kV高压开关柜需求清单
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格</th><th>数量</th><th>单位</th></tr>
        <tr><td>1</td><td>10kV开关柜</td><td>12kV 630A</td><td>2</td><td>面</td></tr>
    </table>
    
    ### 二、升压箱变需求清单
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格</th><th>数量</th><th>单位</th></tr>
        <tr><td>1</td><td>2000kVA光伏升压箱变</td><td>2000kVA 10kV</td><td>4</td><td>套</td></tr>
    </table>
    """
    
    with patch.object(service, "_save_to_db") as mock_save:
        result = service.extract_metadata(multi_table_context, document_id="doc-test-123")
        
        assert len(result.main_equipment_list) == 4
        item_names = [it.item_name for it in result.main_equipment_list]
        assert "10kV开关柜" in item_names
        assert "真空断路器" in item_names
        assert "2000kVA光伏升压箱变" in item_names
        assert "10kV变压器" in item_names
        
        # 验证工况与标准去重汇总
        assert "带电施工" in result.special_working_conditions
        assert "水上作业" in result.special_working_conditions
        assert "GB 50059" in result.mandatory_standards
        assert "GB 50052" in result.mandatory_standards
        
        # 验证自动触发落盘
        mock_save.assert_called_once()
