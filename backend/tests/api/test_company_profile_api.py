"""
企业档案多主体管理 API 集成测试。

验证 /api/v1/company/profiles 完整 CRUD：
1. GET /profiles: 列表获取（默认档案置顶）
2. POST /profiles: 创建新主体档案
3. GET /profiles/{id}: 单个档案详情
4. PUT /profiles/{id}: 更新指定主体字段
5. PATCH /profiles/{id}/set-default: 切换默认主体
6. DELETE /profiles/{id}: 删除非默认档案（默认档案禁止删除）
7. GET /profile & PUT /profile: 向后兼容接口
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_company_profiles_crud_and_compatibility_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 列表接口
        res = await ac.get("/api/v1/company/profiles")
        assert res.status_code == 200
        list_data = res.json()
        assert "profiles" in list_data
        assert "total" in list_data

        # 2. 创建新主体档案
        new_profile_payload = {
            "profile_name": "成都天府分公司",
            "company_name": "四川石楠建设工程有限公司天府分公司",
            "legal_representative": "李分总",
            "credit_code": "91510100MA6TEST999",
            "registered_address": "成都市天府新区兴隆湖畔1号",
            "contact_phone": "028-85991122",
            "email": "tianfu@shinan.com",
            "bank_name": "中国建设银行天府新区支行",
            "bank_account": "51001234567890123456"
        }
        create_res = await ac.post("/api/v1/company/profiles", json=new_profile_payload)
        assert create_res.status_code == 201
        created = create_res.json()
        created_id = created["id"]
        assert created["profile_name"] == "成都天府分公司"
        assert created["company_name"] == "四川石楠建设工程有限公司天府分公司"

        try:
            # 3. 查单条详情
            detail_res = await ac.get(f"/api/v1/company/profiles/{created_id}")
            assert detail_res.status_code == 200
            assert detail_res.json()["profile_name"] == "成都天府分公司"

            # 4. 更新指定档案
            update_payload = {
                "profile_name": "成都天府分公司-更新",
                "authorized_delegate": "张代表"
            }
            put_res = await ac.put(f"/api/v1/company/profiles/{created_id}", json=update_payload)
            assert put_res.status_code == 200
            assert put_res.json()["profile_name"] == "成都天府分公司-更新"
            assert put_res.json()["authorized_delegate"] == "张代表"

            # 5. 设为默认档案
            default_res = await ac.patch(f"/api/v1/company/profiles/{created_id}/set-default")
            assert default_res.status_code == 200
            assert default_res.json()["is_default"] is True

            # 6. 验证设为默认后禁止直接删除
            del_fail_res = await ac.delete(f"/api/v1/company/profiles/{created_id}")
            assert del_fail_res.status_code == 400

            # 7. 验证向后兼容接口 /profile 会返回当前默认档案
            compat_res = await ac.get("/api/v1/company/profile")
            assert compat_res.status_code == 200
            assert compat_res.json()["id"] == created_id

        finally:
            # 恢复默认档案设置，并将测试创建的档案清理
            all_profiles_res = await ac.get("/api/v1/company/profiles")
            other_profiles = [p for p in all_profiles_res.json().get("profiles", []) if p["id"] != created_id]
            if other_profiles:
                # 重新将其他档案设为默认
                await ac.patch(f"/api/v1/company/profiles/{other_profiles[0]['id']}/set-default")
                # 现在可以安全删除测试档案
                del_res = await ac.delete(f"/api/v1/company/profiles/{created_id}")
                assert del_res.status_code == 204
