from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models.user import User
from app.schemas.token import TokenPayload
from app.db.crud import user as crud_user

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login" if hasattr(settings, "API_V1_STR") else "/auth/login"
)
reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login" if hasattr(settings, "API_V1_STR") else "/auth/login",
    auto_error=False
)

def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

def get_current_user_optional(
    db: Session = Depends(get_db), token: Optional[str] = Depends(reusable_oauth2_optional)
) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        return crud_user.user.get(db, id=token_data.sub)
    except Exception:
        return None


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(reusable_oauth2)
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = crud_user.user.get(db, id=token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def get_current_tenant(
    current_user: User = Depends(get_current_active_user),
) -> str:
    """
    Returns the tenant_id from the currently authenticated active user.
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User does not belong to any tenant")
    return current_user.tenant_id

def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Checks if the currently authenticated user has admin privileges.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    return current_user

