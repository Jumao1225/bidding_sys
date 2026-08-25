from unittest.mock import patch

from app.services.metadata.engineering_service import EngineeringSchema, EngineeringService


def test_engineering_extraction_should_pass_tenant_to_each_parallel_llm_call():
    """多表格并发提取时，每个分块调用都必须使用显式租户配置。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(main_equipment_list=[])

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
