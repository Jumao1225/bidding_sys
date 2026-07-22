import pytest
import httpx
from app.main import app

@pytest.mark.asyncio
async def test_create_price_reference_with_extended_fields_should_succeed():
    """测试创建包含品牌、规格、型号、生产厂商、备注的价格参考项"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "item_name": "核心交换机",
            "brand": "华为",
            "spec": "24口千兆电+4口万兆光",
            "model": "S5735-S24T4X",
            "manufacturer": "华为技术有限公司",
            "unit_price": 8500.0,
            "unit": "台",
            "remark": "高可靠性企业级交换机"
        }
        headers = {"X-Tenant-ID": "test-tenant-price"}
        
        # 1. 创建价格项
        create_res = await ac.post("/api/v1/business/price-references", json=payload, headers=headers)
        assert create_res.status_code == 200
        res_json = create_res.json()
        assert res_json["code"] == 200
        created_item = res_json["data"]
        item_id = created_item["id"]
        assert created_item["brand"] == "华为"
        assert created_item["spec"] == "24口千兆电+4口万兆光"
        assert created_item["model"] == "S5735-S24T4X"
        assert created_item["manufacturer"] == "华为技术有限公司"
        assert created_item["remark"] == "高可靠性企业级交换机"

        # 2. 查询价格项列表
        list_res = await ac.get("/api/v1/business/price-references", headers=headers)
        assert list_res.status_code == 200
        items = list_res.json()["data"]
        target = next((item for item in items if item["id"] == item_id), None)
        assert target is not None
        assert target["brand"] == "华为"

        # 3. 更新价格项
        update_payload = {
            "brand": "华三",
            "model": "S5130S-28P-EI"
        }
        update_res = await ac.put(f"/api/v1/business/price-references/{item_id}", json=update_payload, headers=headers)
        assert update_res.status_code == 200
        updated_item = update_res.json()["data"]
        assert updated_item["brand"] == "华三"
        assert updated_item["model"] == "S5130S-28P-EI"

        # 4. 删除价格项
        del_res = await ac.delete(f"/api/v1/business/price-references/{item_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["code"] == 200
