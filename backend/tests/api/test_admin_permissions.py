import uuid
from unittest.mock import patch

import httpx
import pytest

from app.db.crud import user as crud_user
from app.db.session import SessionLocal
from app.main import app
from app.schemas.user import TenantCreate, UserCreate
from app.services.model_config_service import MODEL_CONFIG_KEYS, model_config_service


def _unique_email(prefix: str) -> str:
    """生成本测试独有的登录账号，避免重复运行时撞库。"""
    return f"{prefix}_{uuid.uuid4().hex}@example.com"


@pytest.fixture
def admin_test_data():
    """准备平台管理员、两个租户及租户管理员测试数据。"""
    db = SessionLocal()
    tenant_a = crud_user.tenant.create(
        db,
        obj_in=TenantCreate(name=f"权限测试租户A_{uuid.uuid4().hex}"),
    )
    tenant_b = crud_user.tenant.create(
        db,
        obj_in=TenantCreate(name=f"权限测试租户B_{uuid.uuid4().hex}"),
    )
    platform_admin = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email=_unique_email("platform_admin"),
            password="password123",
            tenant_id=tenant_a.id,
            role="admin",
        ),
    )
    tenant_admin = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email=_unique_email("tenant_admin"),
            password="password123",
            tenant_id=tenant_a.id,
            role="tenant_admin",
        ),
    )
    tenant_b_user = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email=_unique_email("tenant_b_user"),
            password="password123",
            tenant_id=tenant_b.id,
        ),
    )
    try:
        yield tenant_a, tenant_b, platform_admin, tenant_admin, tenant_b_user
    finally:
        try:
            for t_id in [tenant_a.id, tenant_b.id]:
                db.query(crud_user.User).filter(crud_user.User.tenant_id == t_id).delete()
                t_obj = crud_user.tenant.get(db, id=t_id)
                if t_obj:
                    db.delete(t_obj)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


async def _login(client: httpx.AsyncClient, email: str) -> str:
    """登录并返回访问令牌。"""
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_tenant_admin_should_only_list_own_tenant_users(admin_test_data):
    """租户管理员只能看到自己租户的用户。"""
    _, _, _, tenant_admin, tenant_b_user = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, tenant_admin.email)
        response = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    users = response.json()
    assert users
    assert all(user["tenant_id"] == tenant_admin.tenant_id for user in users)
    assert all(user["id"] != tenant_b_user.id for user in users)


@pytest.mark.asyncio
async def test_tenant_admin_should_create_user_and_tenant_admin_in_own_tenant(admin_test_data):
    """租户管理员可以在本租户创建普通用户与租户管理员，但不能跨租户或创建平台管理员。"""
    tenant_a, tenant_b, _, tenant_admin, _ = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, tenant_admin.email)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 成功在本租户创建普通用户
        own_user_response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("own_user"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "user",
                "is_active": True,
            },
            headers=headers,
        )
        # 2. 成功在本租户创建租户管理员
        own_admin_response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("own_admin"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "tenant_admin",
                "is_active": True,
            },
            headers=headers,
        )
        # 3. 跨租户创建被拦截 (403)
        cross_tenant_response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("cross_tenant_user"),
                "password": "password123",
                "tenant_id": tenant_b.id,
                "role": "user",
                "is_active": True,
            },
            headers=headers,
        )
        # 4. 尝试越权创建平台管理员被拦截 (403)
        platform_admin_response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("platform_admin_attempt"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "platform_admin",
                "is_active": True,
            },
            headers=headers,
        )

    assert own_user_response.status_code == 200
    assert own_user_response.json()["role"] == "user"
    assert own_admin_response.status_code == 200
    assert own_admin_response.json()["role"] == "tenant_admin"
    assert cross_tenant_response.status_code == 403
    assert platform_admin_response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_admin_should_not_access_global_tenant_management(admin_test_data):
    """租户管理员不能访问全局租户列表。"""
    _, _, _, tenant_admin, _ = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, tenant_admin.email)
        response = await client.get(
            "/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_should_create_tenant_admin(admin_test_data):
    """平台管理员可以为指定租户创建租户管理员。"""
    tenant_a, _, platform_admin, _, _ = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, platform_admin.email)
        response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("created_tenant_admin"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "tenant_admin",
                "is_active": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "tenant_admin"


@pytest.mark.asyncio
async def test_platform_admin_should_update_tenant_and_role_together(admin_test_data):
    """平台管理员可以在一次操作中变更用户所属租户和租户管理员权限。"""
    tenant_a, tenant_b, platform_admin, _, tenant_b_user = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, platform_admin.email)
        response = await client.put(
            f"/api/v1/admin/users/{tenant_b_user.id}/tenant",
            json={"tenant_id": tenant_a.id, "role": "tenant_admin"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == tenant_a.id
    assert response.json()["role"] == "tenant_admin"


@pytest.mark.asyncio
async def test_platform_admin_should_read_and_update_model_config_in_backend(admin_test_data):
    """平台管理员读取和更新模型配置时应调用后端运行时配置服务。"""
    tenant_a, _, platform_admin, _, _ = admin_test_data
    config_values = {key: f"value-{key.lower()}" for key in MODEL_CONFIG_KEYS}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, platform_admin.email)
        headers = {"Authorization": f"Bearer {token}"}
        with patch.object(model_config_service, "get_effective_values", return_value=config_values), patch.object(
            model_config_service, "update_values", return_value=config_values
        ) as update_mock:
            read_response = await client.get(
                f"/api/v1/admin/model-config?tenant_id={tenant_a.id}", headers=headers
            )
            update_response = await client.put(
                f"/api/v1/admin/model-config?tenant_id={tenant_a.id}",
                json=config_values,
                headers=headers,
            )

    assert read_response.status_code == 200
    assert read_response.json()["data"]["values"] == config_values
    assert update_response.status_code == 200
    assert update_response.json()["data"]["values"] == config_values
    update_mock.assert_called_once_with(
        tenant_id=tenant_a.id,
        values=config_values,
        updated_by_user_id=platform_admin.id,
    )


@pytest.mark.asyncio
async def test_tenant_admin_should_update_own_model_config_only(admin_test_data):
    """租户管理员可以修改本租户模型配置，接口不允许切换到其他租户。"""
    _, tenant_b, _, tenant_admin, _ = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, tenant_admin.email)
        config_values = {key: f"tenant-{key.lower()}" for key in MODEL_CONFIG_KEYS}
        with patch.object(model_config_service, "update_values", return_value=config_values) as update_mock:
            response = await client.put(
                f"/api/v1/admin/model-config?tenant_id={tenant_b.id}",
                json=config_values,
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 200
    assert response.json()["data"]["tenant_id"] == tenant_admin.tenant_id
    update_mock.assert_called_once_with(
        tenant_id=tenant_admin.tenant_id,
        values=config_values,
        updated_by_user_id=tenant_admin.id,
    )


@pytest.mark.asyncio
async def test_admin_status_toggle_permissions(admin_test_data):
    """测试用户状态修改权限：禁止自停用、租户隔离、防越权及正常切换。"""
    tenant_a, tenant_b, platform_admin, tenant_admin, tenant_b_user = admin_test_data
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        t_token = await _login(client, tenant_admin.email)
        t_headers = {"Authorization": f"Bearer {t_token}"}

        # 1. 创建租户 A 内的一个测试用户
        res_create = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("status_user"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "user",
                "is_active": True,
            },
            headers=t_headers,
        )
        assert res_create.status_code == 200
        target_user = res_create.json()

        # 2. 禁止修改自身状态 (400)
        self_res = await client.put(
            f"/api/v1/admin/users/{tenant_admin.id}/status",
            json={"is_active": False},
            headers=t_headers,
        )
        assert self_res.status_code == 400

        # 3. 租户管理员成功停用本租户用户 (200)
        deact_res = await client.put(
            f"/api/v1/admin/users/{target_user['id']}/status",
            json={"is_active": False},
            headers=t_headers,
        )
        assert deact_res.status_code == 200
        assert deact_res.json()["is_active"] is False

        # 4. 租户管理员成功重新启用本租户用户 (200)
        react_res = await client.put(
            f"/api/v1/admin/users/{target_user['id']}/status",
            json={"is_active": True},
            headers=t_headers,
        )
        assert react_res.status_code == 200
        assert react_res.json()["is_active"] is True

        # 5. 租户管理员尝试修改其他租户用户状态被拦截 (403)
        cross_res = await client.put(
            f"/api/v1/admin/users/{tenant_b_user.id}/status",
            json={"is_active": False},
            headers=t_headers,
        )
        assert cross_res.status_code == 403

        # 6. 租户管理员尝试修改平台管理员状态被拦截 (403)
        plat_res = await client.put(
            f"/api/v1/admin/users/{platform_admin.id}/status",
            json={"is_active": False},
            headers=t_headers,
        )
        assert plat_res.status_code == 403


@pytest.mark.asyncio
async def test_admin_delete_user_permissions(admin_test_data):
    """测试用户删除权限：禁止自删、租户隔离、防越权及平台管理员全局删除。"""
    tenant_a, tenant_b, platform_admin, tenant_admin, tenant_b_user = admin_test_data
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        t_token = await _login(client, tenant_admin.email)
        t_headers = {"Authorization": f"Bearer {t_token}"}
        p_token = await _login(client, platform_admin.email)
        p_headers = {"Authorization": f"Bearer {p_token}"}

        # 1. 创建租户 A 内的一个测试用户
        res_create = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("delete_user"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "user",
                "is_active": True,
            },
            headers=t_headers,
        )
        assert res_create.status_code == 200
        target_user = res_create.json()

        # 2. 禁止删除自身账号 (400)
        self_del = await client.delete(
            f"/api/v1/admin/users/{tenant_admin.id}",
            headers=t_headers,
        )
        assert self_del.status_code == 400

        # 3. 租户管理员尝试删除其他租户用户被拦截 (403)
        cross_del = await client.delete(
            f"/api/v1/admin/users/{tenant_b_user.id}",
            headers=t_headers,
        )
        assert cross_del.status_code == 403

        # 4. 租户管理员尝试删除平台管理员被拦截 (403)
        plat_del = await client.delete(
            f"/api/v1/admin/users/{platform_admin.id}",
            headers=t_headers,
        )
        assert plat_del.status_code == 403

        # 5. 租户管理员成功删除所属租户用户 (200)
        own_del = await client.delete(
            f"/api/v1/admin/users/{target_user['id']}",
            headers=t_headers,
        )
        assert own_del.status_code == 200

        # 6. 验证已被删除 (404)
        del_again = await client.delete(
            f"/api/v1/admin/users/{target_user['id']}",
            headers=t_headers,
        )
        assert del_again.status_code == 404

        # 7. 平台管理员可以删除租户 B 用户 (200)
        plat_del_b = await client.delete(
            f"/api/v1/admin/users/{tenant_b_user.id}",
            headers=p_headers,
        )
        assert plat_del_b.status_code == 200


@pytest.mark.asyncio
async def test_platform_admin_toggle_tenant_status(admin_test_data):
    """测试租户启用/停用权限：防自锁、租户管理员越权拦截、状态切换与级联登录封禁。"""
    tenant_a, tenant_b, platform_admin, tenant_admin, tenant_b_user = admin_test_data
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        p_token = await _login(client, platform_admin.email)
        p_headers = {"Authorization": f"Bearer {p_token}"}
        t_token = await _login(client, tenant_admin.email)
        t_headers = {"Authorization": f"Bearer {t_token}"}

        # 1. 平台管理员禁止停用自身所在租户 (400)
        self_disable = await client.put(
            f"/api/v1/admin/tenants/{tenant_a.id}/status",
            json={"is_active": False},
            headers=p_headers,
        )
        assert self_disable.status_code == 400

        # 2. 租户管理员尝试修改租户状态被拦截 (403)
        tenant_admin_attempt = await client.put(
            f"/api/v1/admin/tenants/{tenant_b.id}/status",
            json={"is_active": False},
            headers=t_headers,
        )
        assert tenant_admin_attempt.status_code == 403

        # 3. 平台管理员成功停用租户 B (200)
        disable_res = await client.put(
            f"/api/v1/admin/tenants/{tenant_b.id}/status",
            json={"is_active": False},
            headers=p_headers,
        )
        assert disable_res.status_code == 200
        assert disable_res.json()["is_active"] is False

        # 4. 租户 B 下的用户尝试登录，应被级联封禁拦截 (400)
        b_login_fail = await client.post(
            "/api/v1/auth/login",
            data={"username": tenant_b_user.email, "password": "password123"},
        )
        assert b_login_fail.status_code == 400
        assert "inactive" in b_login_fail.json()["detail"].lower()

        # 5. 平台管理员重新启用租户 B (200)
        enable_res = await client.put(
            f"/api/v1/admin/tenants/{tenant_b.id}/status",
            json={"is_active": True},
            headers=p_headers,
        )
        assert enable_res.status_code == 200
        assert enable_res.json()["is_active"] is True

        # 6. 租户 B 下的用户再次登录成功 (200)
        b_login_success = await client.post(
            "/api/v1/auth/login",
            data={"username": tenant_b_user.email, "password": "password123"},
        )
        assert b_login_success.status_code == 200
        assert "access_token" in b_login_success.json()
