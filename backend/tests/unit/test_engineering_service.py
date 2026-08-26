from unittest.mock import patch
import pytest

from app.services.metadata.engineering_service import EquipmentItem, EngineeringSchema, EngineeringService


def test_engineering_extraction_should_pass_tenant_to_each_parallel_llm_call():
    """多表格并发提取时，每个分块调用都必须使用显式租户配置。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="测试设备", quantity=1, unit="项")]
    )

    # 使用两个最小表格触发 EngineeringService 的并发分块路径。
    source_context = "<table><tr><td>设备</td></tr></table>\n<table><tr><td>材料</td></tr></table>"

    with patch(
        "app.utils.table_utils.extract_equipment_tables_and_context",
        return_value=source_context,
    ), patch.object(service, "_save_to_db"), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ) as generate_mock:
        service.extract_metadata(source_context, "document-a", tenant_id="tenant-a")

    assert generate_mock.call_count == 2
    assert all(call.kwargs["tenant_id"] == "tenant-a" for call in generate_mock.call_args_list)


def test_engineering_extraction_with_empty_table_results_should_raise_error():
    """检测到清单表格但所有分块为空时，应拒绝静默保存空结果。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(main_equipment_list=[])
    source_context = (
        "<table><tr><th>序号</th><th>设备名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>台</td><td>1</td></tr></table>"
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db") as save_mock:
        with pytest.raises(ValueError, match="未产生设备明细"):
            service.extract_metadata(source_context, "document-a")

    save_mock.assert_not_called()


def test_engineering_schema_with_unknown_field_should_raise_validation_error():
    """顶层字段名错误时，应显式报错而不是降级为空清单。"""
    with pytest.raises(ValueError):
        EngineeringSchema.model_validate({"equipment_list": []})


def test_engineering_prompt_should_keep_construction_and_service_boq_rows():
    """工程量清单提取 Prompt 必须覆盖施工、安装和服务类有效行项目。"""
    service = EngineeringService()
    source_context = (
        "<table><tr><th>序号</th><th>项目名称</th><th>单位</th><th>工程量</th></tr>"
        "<tr><td>3.1.6.1</td><td>电缆直埋</td><td>项</td><td>1.00</td></tr>"
        "<tr><td>3.1.7</td><td>交通工程</td><td>项</td><td>1.00</td></tr></table>"
        "在一级动火区域内使用二级动火工作票。工作负责人不在现场时不得作业。"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="电缆直埋", quantity=1, unit="项")]
    )

    with patch.object(
        service, "_save_to_db"
    ), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ) as generate_mock:
        service.extract_metadata(source_context, "document-boq")

    prompt = generate_mock.call_args.kwargs["prompt"]
    assert "BOM/BOQ 清单" in prompt
    assert "施工、运输、调试、检测或其他服务" in prompt
    assert "电缆直埋" in prompt
    assert "交通工程" in prompt
    assert "计价依据门槛（必须同时检查）" in prompt
    assert "安全生产制度、文明施工要求、岗位职责、人员分工" in prompt
    assert "在一级动火区域内使用二级动火工作票" not in prompt
    assert "原文没有数量时必须为 `null`" in prompt


def test_engineering_hierarchy_should_flatten_numbered_boq_siblings():
    """工程量清单分组标题下的连续编号行不应被误判为多级 BOM 子项。"""
    service = EngineeringService()
    items = [
        EquipmentItem(
            item_code="2.6",
            item_name="接地",
            parent_item="乙供设备及材料",
            root_item="乙供设备及材料",
            tree_level=2,
        ),
        EquipmentItem(
            item_code="2.6.1",
            item_name="接地绝缘铜绞线",
            quantity=22850,
            unit="m",
            parent_item="接地",
            root_item="乙供设备及材料",
            tree_level=3,
        ),
        EquipmentItem(
            item_code="2.6.2",
            item_name="接地绝缘铜绞线",
            quantity=3850,
            unit="m",
            parent_item="接地绝缘铜绞线",
            root_item="乙供设备及材料",
            tree_level=4,
        ),
        EquipmentItem(
            item_code="2.6.3",
            item_name="接地干线",
            quantity=25700,
            unit="m",
            parent_item="接地绝缘铜绞线",
            root_item="乙供设备及材料",
            tree_level=5,
        ),
    ]

    normalized = service._normalize_boq_hierarchy(items)

    assert [item.item_code for item in normalized] == ["2.6.1", "2.6.2", "2.6.3"]
    assert all(item.parent_item is None for item in normalized)
    assert all(item.root_item is None for item in normalized)
    assert all(item.tree_level == 1 for item in normalized)
    assert all(item.per_set_quantity is None for item in normalized)
