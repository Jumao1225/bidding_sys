import pytest
import httpx
from app.main import app
from app.db.session import SessionLocal
from app.db.crud import user as crud_user
from app.schemas.user import UserCreate, TenantCreate

@pytest.fixture
def test_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def setup_test_user(test_db):
    # Setup
    tenant = crud_user.tenant.get_by_name(test_db, name="TestAuthTenant")
    if not tenant:
        tenant = crud_user.tenant.create(test_db, obj_in=TenantCreate(name="TestAuthTenant"))
    
    user = crud_user.user.get_by_email(test_db, email="test_auth@example.com")
    if not user:
        user = crud_user.user.create(
            test_db, 
            obj_in=UserCreate(
                email="test_auth@example.com", 
                password="password123", 
                tenant_id=tenant.id
            )
        )
    return user

@pytest.mark.asyncio
async def test_login_success(setup_test_user):
    """测试正确密码登录成功"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/login", data={
            "username": "test_auth@example.com",
            "password": "password123"
        })
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_login_wrong_password(setup_test_user):
    """测试错误密码登录失败"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/login", data={
            "username": "test_auth@example.com",
            "password": "wrongpassword"
        })
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect email or password"
