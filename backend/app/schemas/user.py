from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

# Tenant Schemas
class TenantBase(BaseModel):
    name: str
    domain: Optional[str] = None
    is_active: bool = True

class TenantCreate(TenantBase):
    pass

class TenantUpdate(TenantBase):
    name: Optional[str] = None

class Tenant(TenantBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# User Schemas
class UserBase(BaseModel):
    email: str
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    tenant_id: str

class UserCreate(UserBase):
    password: str

class UserUpdate(UserBase):
    email: Optional[str] = None
    password: Optional[str] = None
    tenant_id: Optional[str] = None

class UserUpdatePassword(BaseModel):
    password: str

class UserUpdateTenant(BaseModel):
    tenant_id: str

class User(UserBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
