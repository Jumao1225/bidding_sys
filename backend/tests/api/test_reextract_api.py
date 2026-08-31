import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user
from app.core.context import current_user_id, current_tenant_id
from app.agents.tools.metadata_tools import extract_financial_info
from app.agents.tools.metadata_tools import extract_engineering_info

@pytest.mark.asyncio
async def test_reextract_invalid_domain_should_return_400():
    """测试请求无效的提取领域，预期返回 400 错误"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/v1/analysis/doc-123/reextract/invalid_domain")
            assert res.status_code == 400
            assert "未知的提取领域" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_reextract_valid_domain_context_setting():
    """测试重新提取领域接口能够正确注入 ContextVar 上下文并成功返回"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    captured_context = {}

    def mock_tool_invoke(input_dict):
        captured_context["user_id"] = current_user_id.get()
        captured_context["tenant_id"] = current_tenant_id.get()
        return '{"budget": {"amount": 1000000}}'

    original_invoke = extract_financial_info.invoke
    object.__setattr__(extract_financial_info, "invoke", mock_tool_invoke)

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=MagicMock()):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/analysis/doc-123/reextract/financial")
                
                assert res.status_code == 200
                res_json = res.json()
                assert res_json["code"] == 200
                assert res_json["data"] == {"budget": {"amount": 1000000}}
                assert captured_context["user_id"] == "user-test-999"
                assert captured_context["tenant_id"] == "tenant-test-888"
    finally:
        object.__setattr__(extract_financial_info, "invoke", original_invoke)
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_reextract_cost_estimation_should_succeed():
    """测试重新匹配 BOM 清单能够执行 cost_node、持久化结果并返回明确提示"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.parsed_metadata = {}

    fake_cost_result = {
        "cost_analysis": {
            "total_cost": 50000.0,
            "budget_status": "预算可控",
            "items": [{"name": "测试设备", "ref_price": 50000.0}]
        }
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("app.agents.nodes.cost_agent.cost_node", return_value=fake_cost_result), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/analysis/doc-123/reextract/cost_estimation")
                
                assert res.status_code == 200
                res_json = res.json()
                assert res_json["code"] == 200
                assert res_json["message"] == "BOM 清单重新匹配成功"
                assert res_json["data"]["total_cost"] == 50000.0
                assert mock_doc.parsed_metadata["cost_analysis"]["total_cost"] == 50000.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reextract_engineering_should_only_extract_equipment_without_cost_matching():
    """测试重新提取设备清单不会联动调用成本匹配节点。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.parsed_metadata = {}
    original_invoke = extract_engineering_info.invoke
    object.__setattr__(extract_engineering_info, "invoke", lambda input_dict: '{"main_equipment_list": [{"item_name": "测试设备", "quantity": 2, "unit": "台"}]}')

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("app.agents.nodes.cost_agent.cost_node") as mock_cost_node:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/analysis/doc-123/reextract/engineering")

                assert res.status_code == 200
                assert res.json()["data"]["main_equipment_list"][0]["item_name"] == "测试设备"
                mock_cost_node.assert_not_called()
    finally:
        object.__setattr__(extract_engineering_info, "invoke", original_invoke)
        app.dependency_overrides.clear()
