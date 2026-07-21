from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.db.crud import user as crud_user
from app.schemas.user import Tenant, TenantCreate, User, UserCreate, UserUpdatePassword, UserUpdateTenant
from app.db.models.user import User as UserModel

router = APIRouter()

# -------------------------------------------------------------------
# Tenant Management
# -------------------------------------------------------------------

@router.get("/tenants", response_model=List[Tenant])
def read_tenants(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Retrieve all tenants. Requires admin privileges.
    """
    tenants = crud_user.tenant.get_multi(db, skip=skip, limit=limit)
    return tenants

@router.post("/tenants", response_model=Tenant)
def create_tenant(
    *,
    db: Session = Depends(deps.get_db),
    tenant_in: TenantCreate,
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Create new tenant. Requires admin privileges.
    """
    tenant = crud_user.tenant.get_by_name(db, name=tenant_in.name)
    if tenant:
        raise HTTPException(
            status_code=400,
            detail="The tenant with this name already exists in the system.",
        )
    tenant = crud_user.tenant.create(db, obj_in=tenant_in)
    return tenant

# -------------------------------------------------------------------
# User Management
# -------------------------------------------------------------------

@router.get("/users", response_model=List[User])
def read_users(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Query(None, description="Filter by tenant ID"),
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Retrieve all users. Can be filtered by tenant_id. Requires admin privileges.
    """
    users = crud_user.user.get_multi(db, skip=skip, limit=limit, tenant_id=tenant_id)
    return users

@router.post("/users", response_model=User)
def create_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: UserCreate,
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Create new user. Requires admin privileges.
    """
    user = crud_user.user.get_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    tenant = crud_user.tenant.get(db, id=user_in.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="The specified tenant does not exist.",
        )
    user = crud_user.user.create(db, obj_in=user_in)
    return user

@router.put("/users/{user_id}/password", response_model=User)
def update_user_password(
    *,
    db: Session = Depends(deps.get_db),
    user_id: str,
    password_in: UserUpdatePassword,
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Update a user's password. Requires admin privileges.
    """
    user = crud_user.user.get(db, id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this ID does not exist in the system.",
        )
    
    # Update password
    from app.core.security import get_password_hash
    user.hashed_password = get_password_hash(password_in.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/users/{user_id}/tenant", response_model=User)
def update_user_tenant(
    *,
    db: Session = Depends(deps.get_db),
    user_id: str,
    tenant_in: UserUpdateTenant,
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    Update a user's tenant. Requires admin privileges.
    """
    user = crud_user.user.get(db, id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this ID does not exist in the system.",
        )
        
    tenant = crud_user.tenant.get(db, id=tenant_in.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="The specified tenant does not exist.",
        )
    
    # Update tenant
    user.tenant_id = tenant_in.tenant_id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
