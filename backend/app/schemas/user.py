from pydantic import BaseModel, EmailStr
from typing import Literal, Optional
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
    # 角色只允许使用系统定义的权限级别，避免通过接口写入未知角色。
    role: Literal["user", "tenant_admin", "admin", "platform_admin"] = "user"
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

class UserUpdateStatus(BaseModel):
    is_active: bool

class UserUpdateTenant(BaseModel):
    tenant_id: str
    # 该接口只允许平台管理员调整普通用户与租户管理员权限。
    role: Optional[Literal["user", "tenant_admin"]] = None

class User(UserBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
