from pydantic import BaseModel
from typing import Optional, List

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    tenant_id: Optional[str] = None

from app.schemas.user import User

class TenantSelectionOption(BaseModel):
    id: str
    name: str
    role: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    user: Optional[User] = None
    require_tenant_selection: Optional[bool] = False
    message: Optional[str] = None
    tenants: Optional[List[TenantSelectionOption]] = None
