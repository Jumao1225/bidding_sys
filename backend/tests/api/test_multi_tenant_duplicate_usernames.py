import uuid
import httpx
import pytest
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import SessionLocal
from app.db.crud import user as crud_user
from app.schemas.user import TenantCreate, UserCreate


@pytest.fixture
def duplicate_username_test_env():
    """
    准备测试环境：创建两个企业租户，并在测试结束后自动 teardown 清理。
    """
    db = SessionLocal()
    tenant_a = crud_user.tenant.create(
        db,
        obj_in=TenantCreate(name=f"重名测试企业A_{uuid.uuid4().hex[:8]}"),
    )
    tenant_b = crud_user.tenant.create(
        db,
        obj_in=TenantCreate(name=f"重名测试企业B_{uuid.uuid4().hex[:8]}"),
    )
    
    # 在企业A和企业B分别创建名为 operator 的同名普通用户，密码不同
    user_a = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email="operator",
            password="passwordA123",
            tenant_id=tenant_a.id,
            role="user",
        ),
    )
    user_b = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email="operator",
            password="passwordB456",
            tenant_id=tenant_b.id,
            role="user",
        ),
    )
    
    # 在企业A创建一个专属管理员
    admin_a = crud_user.user.create(
        db,
        obj_in=UserCreate(
            email=f"admin_a_{uuid.uuid4().hex[:6]}",
            password="password123",
            tenant_id=tenant_a.id,
            role="tenant_admin",
        ),
    )

    try:
        yield tenant_a, tenant_b, user_a, user_b, admin_a
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


@pytest.mark.asyncio
async def test_multi_tenant_duplicate_user_creation_and_rejection(duplicate_username_test_env):
    """
    测试：不同企业允许创建同名账号，但同一个企业内部再次创建同名账号必须被 400 拦截。
    """
    tenant_a, tenant_b, user_a, user_b, admin_a = duplicate_username_test_env

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # 1. 使用企业A管理员登录
        login_res = await client.post(
            "/api/v1/auth/login",
            data={"username": admin_a.email, "password": "password123"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 尝试在企业A内部再次创建名为 operator 的账号 -> 应被 400 拒绝
        duplicate_res = await client.post(
            "/api/v1/admin/users",
            headers=headers,
            json={
                "email": "operator",
                "password": "newpassword123",
                "tenant_id": tenant_a.id,
                "role": "user",
            },
        )
        assert duplicate_res.status_code == 400
        assert "already exists in this tenant" in duplicate_res.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_user_login_with_different_passwords(duplicate_username_test_env):
    """
    测试：当企业A和企业B都叫 operator 且密码不同时：
    输入 passwordA123 自动识别企业A并登录；
    输入 passwordB456 自动识别企业B并登录。
    """
    tenant_a, tenant_b, user_a, user_b, admin_a = duplicate_username_test_env

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # 1. 输入账号 operator + 企业A密码
        res_a = await client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "passwordA123"},
        )
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["user"]["tenant_id"] == tenant_a.id

        # 2. 输入账号 operator + 企业B密码
        res_b = await client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "passwordB456"},
        )
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["user"]["tenant_id"] == tenant_b.id


@pytest.mark.asyncio
async def test_duplicate_user_login_with_same_password_should_prompt_tenant_selection(duplicate_username_test_env):
    """
    测试：当企业A和企业B的 operator 设置了完全相同的密码时：
    未指定企业直接登录 -> 后端返回 require_tenant_selection: True 与候选企业列表；
    带上 tenant_id 或联合格式登录 -> 精准直接登入指定企业。
    """
    tenant_a, tenant_b, user_a, user_b, admin_a = duplicate_username_test_env

    # 将 user_b 的密码也改成 passwordA123，使其在两家企业密码完全相同
    db = SessionLocal()
    from app.core.security import get_password_hash
    u_b = crud_user.user.get(db, id=user_b.id)
    u_b.hashed_password = get_password_hash("passwordA123")
    db.add(u_b)
    db.commit()
    db.close()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # 1. 仅输入账号和密码 -> 应触发企业选择模式
        res = await client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "passwordA123"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("require_tenant_selection") is True
        assert len(data.get("tenants", [])) == 2
        tenant_ids = [t["id"] for t in data["tenants"]]
        assert tenant_a.id in tenant_ids
        assert tenant_b.id in tenant_ids

        # 2. 携带 tenant_id 选择企业A登录 -> 成功进入企业A
        res_selected = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "operator",
                "password": "passwordA123",
                "tenant_id": tenant_a.id,
            },
        )
        assert res_selected.status_code == 200
        selected_data = res_selected.json()
        assert selected_data["user"]["tenant_id"] == tenant_a.id

        # 3. 使用联合前缀 '企业名称/用户名' 登录 -> 成功进入企业B
        res_prefix = await client.post(
            "/api/v1/auth/login",
            data={
                "username": f"{tenant_b.name}/operator",
                "password": "passwordA123",
            },
        )
        assert res_prefix.status_code == 200
        prefix_data = res_prefix.json()
        assert prefix_data["user"]["tenant_id"] == tenant_b.id
