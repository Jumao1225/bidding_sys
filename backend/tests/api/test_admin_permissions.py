import uuid

import httpx
import pytest

from app.db.crud import user as crud_user
from app.db.session import SessionLocal
from app.main import app
from app.schemas.user import TenantCreate, UserCreate


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
async def test_tenant_admin_should_create_only_regular_user_in_own_tenant(admin_test_data):
    """租户管理员只能在本租户创建普通用户。"""
    tenant_a, tenant_b, _, tenant_admin, _ = admin_test_data
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, tenant_admin.email)
        headers = {"Authorization": f"Bearer {token}"}

        own_response = await client.post(
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
        elevated_response = await client.post(
            "/api/v1/admin/users",
            json={
                "email": _unique_email("elevated_user"),
                "password": "password123",
                "tenant_id": tenant_a.id,
                "role": "tenant_admin",
                "is_active": True,
            },
            headers=headers,
        )

    assert own_response.status_code == 200
    assert own_response.json()["role"] == "user"
    assert cross_tenant_response.status_code == 403
    assert elevated_response.status_code == 403


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
