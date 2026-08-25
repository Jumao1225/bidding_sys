from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.db.crud import user as crud_user
from app.schemas.user import Tenant, TenantCreate, User, UserCreate, UserUpdatePassword, UserUpdateTenant
from app.db.models.user import User as UserModel
from loguru import logger

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
    current_manager: UserModel = Depends(deps.get_current_user_manager),
) -> Any:
    """
    Retrieve all users. Can be filtered by tenant_id. Requires admin privileges.
    """
    # 租户管理员只能看到自己租户的用户，忽略客户端传入的跨租户筛选条件。
    effective_tenant_id = tenant_id
    if current_manager.role == "tenant_admin":
        effective_tenant_id = current_manager.tenant_id
        if tenant_id and tenant_id != current_manager.tenant_id:
            logger.warning("租户管理员 {} 尝试查询其他租户用户", current_manager.id)
    users = crud_user.user.get_multi(db, skip=skip, limit=limit, tenant_id=effective_tenant_id)
    return users

@router.post("/users", response_model=User)
def create_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: UserCreate,
    current_manager: UserModel = Depends(deps.get_current_user_manager),
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
    if current_manager.role == "tenant_admin":
        if user_in.tenant_id != current_manager.tenant_id:
            logger.warning("租户管理员 {} 尝试向其他租户创建用户", current_manager.id)
            raise HTTPException(status_code=403, detail="Tenant administrators can only manage their own tenant")
        if user_in.role != "user":
            logger.warning("租户管理员 {} 尝试创建角色 {}", current_manager.id, user_in.role)
            raise HTTPException(status_code=403, detail="Tenant administrators can only create regular users")
    user = crud_user.user.create(db, obj_in=user_in)
    logger.info("管理员 {} 在租户 {} 创建用户 {}，角色为 {}", current_manager.id, user.tenant_id, user.id, user.role)
    return user

@router.put("/users/{user_id}/password", response_model=User)
def update_user_password(
    *,
    db: Session = Depends(deps.get_db),
    user_id: str,
    password_in: UserUpdatePassword,
    current_manager: UserModel = Depends(deps.get_current_user_manager),
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
    if current_manager.role == "tenant_admin" and user.tenant_id != current_manager.tenant_id:
        logger.warning("租户管理员 {} 尝试修改其他租户用户密码", current_manager.id)
        raise HTTPException(status_code=403, detail="Tenant administrators can only manage their own tenant")
    
    # Update password
    from app.core.security import get_password_hash
    user.hashed_password = get_password_hash(password_in.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("管理员 {} 修改了用户 {} 的密码", current_manager.id, user.id)
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

    # 平台管理员账号不能通过租户变更入口被降权，避免误操作导致平台失管。
    if user.role in deps.PLATFORM_ADMIN_ROLES and tenant_in.role is not None:
        logger.warning("平台管理员 {} 尝试通过租户变更入口修改平台账号 {} 的权限", current_admin.id, user.id)
        raise HTTPException(status_code=400, detail="Platform administrator role cannot be changed here")
        
    tenant = crud_user.tenant.get(db, id=tenant_in.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="The specified tenant does not exist.",
        )
    
    # 租户与业务角色在同一个事务中更新，确保界面上的“变更租户+权限”不会出现半成功状态。
    user.tenant_id = tenant_in.tenant_id
    if tenant_in.role is not None:
        user.role = tenant_in.role
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("平台管理员 {} 将用户 {} 调整到租户 {}，角色为 {}", current_admin.id, user.id, user.tenant_id, user.role)
    return user


# -------------------------------------------------------------------
# LLM Cost & Usage Statistics (大模型调用全量花费与 Token 统计 API)
# -------------------------------------------------------------------

@router.get("/llm-cost-stats")
def get_llm_cost_stats(
    db: Session = Depends(deps.get_db),
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    全系统大模型 (LLM) 调用全景统计与费用估算 API。
    统计包括：主控 Agent 审计日志、标书起草 Multi-Worker Agent、标书打分 3 轮共识机制等。
    """
    import os
    from app.db.models.audit import AgentAuditLog
    from app.db.models.bid_score import BidScoreResult, BidScoreItem
    from app.core.config import settings

    # 1. 审计日志统计 (模块一)
    audit_logs = db.query(AgentAuditLog).all()
    llm_logs = [l for l in audit_logs if l.action_type in ('llm_call', 'llm_call_text', 'llm_call_structured', 'llm_call_worker')]

    m1_prompt = sum(l.prompt_tokens or 0 for l in llm_logs)
    m1_completion = sum(l.completion_tokens or 0 for l in llm_logs)
    m1_total = sum(l.total_tokens or ((l.prompt_tokens or 0) + (l.completion_tokens or 0)) for l in llm_logs)

    # 2. 标书起草模块统计 (模块二)
    drafts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads", "drafts"
    )
    draft_count = 0
    if os.path.exists(drafts_dir):
        draft_count = len([f for f in os.listdir(drafts_dir) if f.endswith('.docx')])

    m2_prompt = draft_count * 400_000
    m2_completion = draft_count * 100_000
    m2_total = m2_prompt + m2_completion

    # 3. 标书打分模块统计 (模块三)
    score_items_count = db.query(BidScoreItem).count()
    score_results_count = db.query(BidScoreResult).count()
    total_scoring_calls = score_items_count * 3

    m3_prompt = total_scoring_calls * 2500
    m3_completion = total_scoring_calls * 200
    m3_total = m3_prompt + m3_completion

    # 汇总
    grand_prompt = m1_prompt + m2_prompt + m3_prompt
    grand_completion = m1_completion + m2_completion + m3_completion
    grand_total = grand_prompt + grand_completion

    # 费用计算
    ds_cost_rmb = (grand_prompt / 1_000_000) * 1.0 + (grand_completion / 1_000_000) * 2.0
    ds_cache_cost_rmb = ((grand_prompt * 0.8 / 1_000_000) * 0.1 + (grand_prompt * 0.2 / 1_000_000) * 1.0) + (grand_completion / 1_000_000) * 2.0
    gpt4o_cost_usd = (grand_prompt / 1_000_000) * 2.50 + (grand_completion / 1_000_000) * 10.00
    qwen_cost_rmb = (grand_prompt / 1_000_000) * 0.30 + (grand_completion / 1_000_000) * 0.60

    return {
        "code": 200,
        "message": "全系统 LLM 花费与 Token 统计成功",
        "data": {
            "configured_model": settings.LLM_MODEL_NAME,
            "overall_summary": {
                "grand_total_tokens": grand_total,
                "grand_prompt_tokens": grand_prompt,
                "grand_completion_tokens": grand_completion,
                "formatted_total_tokens": f"{grand_total / 1_000_000:.2f} M Tokens"
            },
            "module_breakdown": {
                "agent_orchestrator": {
                    "calls_count": len(llm_logs),
                    "prompt_tokens": m1_prompt,
                    "completion_tokens": m1_completion,
                    "total_tokens": m1_total
                },
                "bid_filler_agent": {
                    "draft_docx_files": draft_count,
                    "estimated_prompt_tokens": m2_prompt,
                    "estimated_completion_tokens": m2_completion,
                    "estimated_total_tokens": m2_total
                },
                "bid_scorer_agent": {
                    "evaluated_reports": score_results_count,
                    "evaluated_items": score_items_count,
                    "scoring_llm_calls": total_scoring_calls,
                    "estimated_prompt_tokens": m3_prompt,
                    "estimated_completion_tokens": m3_completion,
                    "estimated_total_tokens": m3_total
                }
            },
            "cost_estimations": {
                "deepseek_v3_standard_rmb": round(ds_cost_rmb, 4),
                "deepseek_v3_cached_rmb": round(ds_cache_cost_rmb, 4),
                "gpt4o_usd": round(gpt4o_cost_usd, 4),
                "gpt4o_rmb_equivalent": round(gpt4o_cost_usd * 7.2, 4),
                "qwen_flash_rmb": round(qwen_cost_rmb, 4)
            }
        }
    }


@router.post("/clean-office-processes")
def clean_office_processes(
    current_admin: UserModel = Depends(deps.get_current_admin_user),
) -> Any:
    """
    运维管理 API：强制清理 Windows/Linux 系统中残留悬挂的 OfficeCLI / LibreOffice 孤儿进程，强行释放文件独占锁
    """
    from app.services.office_cli_service import office_cli_service

    killed_count = office_cli_service.kill_lingering_processes()
    return {
        "code": 200,
        "message": f"成功解封句柄锁并强杀 {killed_count} 个悬挂的 Office 孤儿进程",
        "data": {"killed_count": killed_count}
    }
