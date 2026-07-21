from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core import security
from app.schemas.token import Token, LoginResponse
from app.db.crud import user as crud_user

from app.schemas.user import User

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
def login_access_token(
    db: Session = Depends(deps.get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = crud_user.user.get_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # We embed the tenant_id directly into the JWT token payload
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires, tenant_id=user.tenant_id
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }
