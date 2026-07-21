from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    tenant_id: Optional[str] = None

from app.schemas.user import User

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: User
