"""
Enterprise Company Profile Endpoints

提供企业基础档案的查询 (GET) 与更新 (PUT) 接口，直接对盘 PostgreSQL 中的 company_profiles 数据表。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models.business import CompanyProfileModel
from app.schemas.company_profile import CompanyProfileResponse, CompanyProfileUpdate

router = APIRouter()


@router.get("/profile", response_model=CompanyProfileResponse, summary="获取企业基础档案")
def get_company_profile(db: Session = Depends(get_db)):
    """
    获取 PostgreSQL 物理数据库中的企业基础档案记录
    """
    profile = db.query(CompanyProfileModel).first()
    if not profile:
        # 若数据库中无记录，自动创建初始空档案记录
        profile = CompanyProfileModel()
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


@router.put("/profile", response_model=CompanyProfileResponse, summary="更新企业基础档案")
def update_company_profile(
    profile_in: CompanyProfileUpdate,
    db: Session = Depends(get_db)
):
    """
    更新 PostgreSQL 物理数据库中的企业基础档案记录
    """
    profile = db.query(CompanyProfileModel).first()
    if not profile:
        profile = CompanyProfileModel()
        db.add(profile)

    update_data = profile_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile
