from datetime import timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core import security
from app.schemas.token import Token, LoginResponse
from app.db.crud import user as crud_user
from app.schemas.user import User
from loguru import logger

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
def login_access_token(
    db: Session = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
    tenant_id: Optional[str] = Form(None),
) -> Any:
    """
    OAuth2 兼容的登录认证接口。
    支持：
    1. 唯一账号智能直登
    2. '企业名称/用户名' 或 '企业ID/用户名' 联合账号登录
    3. 跨租户同名账号返回企业候选列表供前端弹窗选择
    """
    raw_username = form_data.username.strip()
    target_tenant_identifier = tenant_id.strip() if tenant_id else None
    email = raw_username

    # 1. 优先解析联合输入格式（例如 企业A/zhangsan 或 企业A\zhangsan）
    if "/" in raw_username:
        parts = raw_username.split("/", 1)
        target_tenant_identifier = parts[0].strip()
        email = parts[1].strip()
    elif "\\" in raw_username:
        parts = raw_username.split("\\", 1)
        target_tenant_identifier = parts[0].strip()
        email = parts[1].strip()

    user = None

    # 2. 如果指定了具体企业标识（通过参数或前缀）：
    if target_tenant_identifier:
        target_tenant = crud_user.tenant.get_by_identifier(db, target_tenant_identifier)
        if not target_tenant:
            logger.warning("用户尝试登录不存在的企业租户: {}", target_tenant_identifier)
            raise HTTPException(status_code=400, detail="指定的企业租户不存在")
        
        user = crud_user.user.get_by_tenant_and_email(db, tenant_id=target_tenant.id, email=email)
        if not user or not security.verify_password(form_data.password, user.hashed_password):
            raise HTTPException(status_code=400, detail="账号或密码错误")
    else:
        # 3. 未显式指定企业：在全系统检索同名账号
        candidates = crud_user.user.get_multi_by_email(db, email=email)
        if not candidates:
            raise HTTPException(status_code=400, detail="账号或密码错误")

        # 校验密码并筛选出凭证匹配的账号列表
        matched_users = [
            u for u in candidates 
            if security.verify_password(form_data.password, u.hashed_password)
        ]

        if not matched_users:
            raise HTTPException(status_code=400, detail="账号或密码错误")

        if len(matched_users) == 1:
            # 只有一家企业账号密码匹配，直接登录
            user = matched_users[0]
        else:
            # 存在跨企业同名账号且密码有效，返回候选企业列表供前端弹窗选择
            tenants_list = []
            for u in matched_users:
                t_name = u.tenant.name if u.tenant else "默认空间"
                tenants_list.append({
                    "id": u.tenant_id,
                    "name": t_name,
                    "role": u.role,
                })
            
            logger.info("账号 {} 在多个企业存在，返回企业选择列表: {}", email, [t['name'] for t in tenants_list])
            return {
                "require_tenant_selection": True,
                "message": "检测到您在多个企业存在账号，请选择要进入的企业空间",
                "tenants": tenants_list,
            }

    # 4. 账号状态与租户状态校验
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user / 账号已被停用，请联系管理员")
    elif user.tenant and not user.tenant.is_active and user.role not in deps.PLATFORM_ADMIN_ROLES:
        raise HTTPException(status_code=400, detail="Tenant is inactive / 所属企业租户已被停用，无法登录")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires, tenant_id=user.tenant_id
    )

    logger.info("用户 {} (租户: {}) 成功登录", user.email, user.tenant_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }
