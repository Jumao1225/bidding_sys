import pytest
import httpx
from app.main import app
from app.db.session import SessionLocal
from app.db.crud import user as crud_user
from app.db.crud.qualification import qualification_crud
from app.schemas.user import UserCreate, TenantCreate
from app.schemas.qualification import QualificationCreate

@pytest.fixture
def test_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def setup_tenants_and_users(test_db):
    # Tenant A
    tenant_a = crud_user.tenant.get_by_name(test_db, name="Tenant_A")
    if not tenant_a:
        tenant_a = crud_user.tenant.create(test_db, obj_in=TenantCreate(name="Tenant_A"))
    
    user_a = crud_user.user.get_by_email(test_db, email="user_a@example.com")
    if not user_a:
        user_a = crud_user.user.create(
            test_db, 
            obj_in=UserCreate(email="user_a@example.com", password="password123", tenant_id=tenant_a.id)
        )

    # Tenant B
    tenant_b = crud_user.tenant.get_by_name(test_db, name="Tenant_B")
    if not tenant_b:
        tenant_b = crud_user.tenant.create(test_db, obj_in=TenantCreate(name="Tenant_B"))
    
    user_b = crud_user.user.get_by_email(test_db, email="user_b@example.com")
    if not user_b:
        user_b = crud_user.user.create(
            test_db, 
            obj_in=UserCreate(email="user_b@example.com", password="password123", tenant_id=tenant_b.id)
        )

    # Create a qualification for Tenant A
    qual = qualification_crud.create_qualification(
        db=test_db,
        obj_in=QualificationCreate(
            name="Test Qual",
            company_name="Company A"
        ),
        tenant_id=tenant_a.id,
        user_id=user_a.id
    )

    return user_a, user_b, qual

@pytest.mark.asyncio
async def test_tenant_isolation(setup_tenants_and_users):
    """测试不同租户之间的数据隔离"""
    user_a, user_b, qual_a = setup_tenants_and_users
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # Login User A
        res_a = await ac.post("/api/v1/auth/login", data={"username": "user_a@example.com", "password": "password123"})
        token_a = res_a.json()["access_token"]
        
        # Login User B
        res_b = await ac.post("/api/v1/auth/login", data={"username": "user_b@example.com", "password": "password123"})
        token_b = res_b.json()["access_token"]
        
        # User A accesses qualifications -> should see qual_a
        req_a = await ac.get("/api/v1/qualifications/", headers={"Authorization": f"Bearer {token_a}"})
        assert req_a.status_code == 200
        quals_a = req_a.json()["data"]
        assert len(quals_a) >= 1
        assert any(q["id"] == qual_a.id for q in quals_a)
        
        # User B accesses qualifications -> should NOT see qual_a
        req_b = await ac.get("/api/v1/qualifications/", headers={"Authorization": f"Bearer {token_b}"})
        assert req_b.status_code == 200
        quals_b = req_b.json()["data"]
        assert not any(q["id"] == qual_a.id for q in quals_b)
