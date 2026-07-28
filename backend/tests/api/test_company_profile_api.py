import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_get_and_update_company_profile_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 测试 GET /api/v1/company/profile
        get_res = await ac.get("/api/v1/company/profile")
        assert get_res.status_code == 200
        data = get_res.json()
        assert "company_name" in data
        assert "credit_code" in data

        # 2. 测试 PUT /api/v1/company/profile
        update_payload = {
            "company_name": "成都石楠建设工程有限公司",
            "legal_representative": "王五",
            "contact_phone": "028-88889999"
        }
        put_res = await ac.put("/api/v1/company/profile", json=update_payload)
        assert put_res.status_code == 200
        updated_data = put_res.json()
        assert updated_data["company_name"] == "成都石楠建设工程有限公司"
        assert updated_data["legal_representative"] == "王五"
        assert updated_data["contact_phone"] == "028-88889999"

        # 复原修改
        restore_payload = {
            "company_name": "四川石楠建设工程有限公司",
            "legal_representative": "张三",
            "contact_phone": "028-85123456"
        }
        await ac.put("/api/v1/company/profile", json=restore_payload)
