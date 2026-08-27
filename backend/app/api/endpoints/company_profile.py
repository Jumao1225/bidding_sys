"""
企业基础档案管理接口 (Company Profile CRUD)

提供多主体企业档案的完整增删改查能力，支持列表管理、默认档案切换。
同时保留向后兼容的单数路径 (/profile) 供旧客户端和 Agent 工具使用。
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models.business import CompanyProfileModel
from app.schemas.company_profile import (
    CompanyProfileCreate,
    CompanyProfileUpdate,
    CompanyProfileResponse,
    CompanyProfileListResponse,
)
from loguru import logger

router = APIRouter()


# ============================================================
# 多主体 CRUD 接口 (/profiles)
# ============================================================

@router.get(
    "/profiles",
    response_model=CompanyProfileListResponse,
    summary="获取企业档案列表",
)
def list_company_profiles(db: Session = Depends(get_db)):
    """
    获取所有企业档案，按 is_default DESC, created_at DESC 排序。
    默认档案始终排在第一位。
    """
    profiles = (
        db.query(CompanyProfileModel)
        .order_by(CompanyProfileModel.is_default.desc(), CompanyProfileModel.created_at.desc())
        .all()
    )
    logger.info("查询企业档案列表，共 {} 条记录", len(profiles))
    return CompanyProfileListResponse(profiles=profiles, total=len(profiles))


@router.get(
    "/profiles/{profile_id}",
    response_model=CompanyProfileResponse,
    summary="获取单个企业档案详情",
)
def get_company_profile_by_id(profile_id: str, db: Session = Depends(get_db)):
    """根据 ID 获取单条企业档案记录。"""
    profile = db.query(CompanyProfileModel).filter(CompanyProfileModel.id == profile_id).first()
    if not profile:
        logger.warning("企业档案不存在: profile_id={}", profile_id)
        raise HTTPException(status_code=404, detail="企业档案不存在")
    return profile


@router.post(
    "/profiles",
    response_model=CompanyProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建新的企业档案",
)
def create_company_profile(
    profile_in: CompanyProfileCreate,
    db: Session = Depends(get_db),
):
    """
    创建一条新的企业档案。
    如果系统中尚无任何档案，首条记录自动设为默认。
    """
    # 检查是否为首条记录
    existing_count = db.query(CompanyProfileModel).count()
    is_first = existing_count == 0

    profile = CompanyProfileModel(
        is_default=is_first,
        **profile_in.model_dump(),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    logger.info(
        "创建企业档案成功: id={}, name='{}', is_default={}",
        profile.id, profile.profile_name, profile.is_default,
    )
    return profile


@router.put(
    "/profiles/{profile_id}",
    response_model=CompanyProfileResponse,
    summary="更新指定企业档案",
)
def update_company_profile_by_id(
    profile_id: str,
    profile_in: CompanyProfileUpdate,
    db: Session = Depends(get_db),
):
    """更新指定 ID 的企业档案字段。"""
    profile = db.query(CompanyProfileModel).filter(CompanyProfileModel.id == profile_id).first()
    if not profile:
        logger.warning("更新失败，企业档案不存在: profile_id={}", profile_id)
        raise HTTPException(status_code=404, detail="企业档案不存在")

    update_data = profile_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(profile, field, value)

    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)

    logger.info("更新企业档案成功: id={}, name='{}'", profile.id, profile.profile_name)
    return profile


@router.delete(
    "/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除指定企业档案",
)
def delete_company_profile(profile_id: str, db: Session = Depends(get_db)):
    """
    删除指定企业档案。
    默认档案不允许直接删除，需先将另一个档案设为默认。
    """
    profile = db.query(CompanyProfileModel).filter(CompanyProfileModel.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="企业档案不存在")

    if profile.is_default:
        logger.warning("尝试删除默认档案被拒绝: profile_id={}", profile_id)
        raise HTTPException(
            status_code=400,
            detail="默认档案不允许删除，请先将另一个档案设为默认后再删除此档案",
        )

    db.delete(profile)
    db.commit()
    logger.info("删除企业档案成功: id={}, name='{}'", profile_id, profile.profile_name)
    return None


@router.patch(
    "/profiles/{profile_id}/set-default",
    response_model=CompanyProfileResponse,
    summary="将指定档案设为默认",
)
def set_default_profile(profile_id: str, db: Session = Depends(get_db)):
    """
    将指定档案设为默认，同时取消其他档案的默认状态。
    确保同一时刻只有一条默认档案。
    """
    target = db.query(CompanyProfileModel).filter(CompanyProfileModel.id == profile_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="企业档案不存在")

    # 先取消所有档案的默认状态
    db.query(CompanyProfileModel).filter(CompanyProfileModel.is_default == True).update(
        {"is_default": False, "updated_at": datetime.now(timezone.utc)}
    )
    # 再将目标档案设为默认
    target.is_default = True
    target.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target)

    logger.info("设置默认档案成功: id={}, name='{}'", target.id, target.profile_name)
    return target


# ============================================================
# 向后兼容接口 (/profile 单数) — 旧 Agent 工具和前端仍可使用
# ============================================================

@router.get("/profile", response_model=CompanyProfileResponse, summary="[兼容] 获取默认企业档案")
def get_company_profile(db: Session = Depends(get_db)):
    """
    向后兼容接口：返回默认档案。
    若无默认档案则返回最早创建的一条；若无任何记录则自动创建空档案。
    """
    profile = db.query(CompanyProfileModel).filter(CompanyProfileModel.is_default == True).first()
    if not profile:
        profile = db.query(CompanyProfileModel).order_by(CompanyProfileModel.created_at.asc()).first()
    if not profile:
        # 兼容旧行为：自动创建空档案
        profile = CompanyProfileModel(
            profile_name="默认企业档案",
            is_default=True,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        logger.info("企业档案不存在，已创建空默认档案记录: {}", profile.id)

    return profile


@router.put("/profile", response_model=CompanyProfileResponse, summary="[兼容] 更新默认企业档案")
def update_company_profile(
    profile_in: CompanyProfileUpdate,
    db: Session = Depends(get_db),
):
    """
    向后兼容接口：更新默认档案。
    """
    profile = db.query(CompanyProfileModel).filter(CompanyProfileModel.is_default == True).first()
    if not profile:
        profile = db.query(CompanyProfileModel).order_by(CompanyProfileModel.created_at.asc()).first()
    if not profile:
        # 兼容旧行为：自动创建
        profile = CompanyProfileModel(profile_name="默认企业档案", is_default=True)
        db.add(profile)
        logger.info("企业档案不存在，更新请求将创建新默认档案记录")

    update_data = profile_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(profile, field, value)

    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    logger.info("企业档案(兼容)更新成功: {}", profile.id)
    return profile
