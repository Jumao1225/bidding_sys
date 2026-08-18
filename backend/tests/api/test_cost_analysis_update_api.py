import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user
from app.db.models.metadata import FinancialMetadata

@pytest.mark.asyncio
async def test_update_cost_analysis_should_succeed():
    """测试手动更新 BOM 成本核算明细与自定义费用分项，验证小计、总成本重算与持久化落盘"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {"budget_limit": "100000"}

    payload = {
        "items": [
            {
                "name": "并网柜",
                "spec_requirement": "10kV 并网柜",
                "qty": 2,
                "unit": "台",
                "ref_price": 20000.0,
                "matched_name": "并网柜",
                "matched_brand": "正泰",
                "match_quality": "精准匹配"
            },
            {
                "name": "现场施工人工费",
                "spec_requirement": "含设备安装调试与调班人工费",
                "qty": 1,
                "unit": "项",
                "ref_price": 15000.0,
                "match_quality": "手动添加"
            },
            {
                "name": "售后运维服务费",
                "spec_requirement": "3年免费质保与定期维保服务",
                "qty": 1,
                "unit": "项",
                "ref_price": 5000.0,
                "match_quality": "手动添加"
            }
        ],
        "analysis_summary": "手动补充施工与售后维保服务费用。"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-123/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                assert res_json["code"] == 200
                
                data = res_json["data"]
                # 2*20000 + 15000 + 5000 = 60000.0
                assert data["total_cost"] == 60000.0
                assert len(data["items"]) == 3
                assert data["items"][1]["name"] == "现场施工人工费"
                assert data["items"][1]["subtotal"] == 15000.0
                assert data["items"][2]["name"] == "售后运维服务费"
                assert data["items"][2]["subtotal"] == 5000.0
                assert "可控" in data["budget_status"]
                
                # 验证 mock_doc 中的 parsed_metadata 正确持久化
                saved_cost = mock_doc.parsed_metadata["cost_analysis"]
                assert saved_cost["total_cost"] == 60000.0
                assert len(saved_cost["items"]) == 3
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_update_cost_analysis_with_financial_max_price_limit_exceeded():
    """测试当 FinancialMetadata 存在最高投标限价，且人工修改总成本超出限额时，精准返回已超出最高限价与超额金额"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    # Mock FinancialMetadata
    mock_fin = MagicMock(spec=FinancialMetadata)
    mock_fin.max_price_limit = {"amount": 50000.0, "currency": "CNY"}
    mock_fin.budget = {"amount": 60000.0, "currency": "CNY"}

    payload = {
        "items": [
            {
                "name": "高规格逆变器",
                "qty": 2,
                "ref_price": 30000.0,
                "unit": "台"
            }
        ],
        "analysis_summary": "人工调整为高规格逆变器"
    }

    mock_db_session = MagicMock()
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_fin
    from app.api.endpoints.analysis import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session

    try:
        transport = httpx.ASGITransport(app=app)
        
        # Mock DB 查询 FinancialMetadata
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-exceed/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                data = res_json["data"]
                
                # 总成本 60000.0 > 最高限价 50000.0，超额 10000.0
                assert data["total_cost"] == 60000.0
                assert data["budget_numeric"] == 50000.0
                assert data["limit_type"] == "max_price_limit"
                assert "已超出最高投标限价" in data["budget_status"]
                assert "10,000.00" in data["budget_status"] or "10000" in data["budget_status"]
    finally:
        app.dependency_overrides.clear()

