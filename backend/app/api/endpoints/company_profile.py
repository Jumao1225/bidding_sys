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
        # 若数据库中无记录，自动创建初始档案记录
        profile = CompanyProfileModel(
            company_name="四川石楠建设工程有限公司",
            legal_representative="张三",
            authorized_delegate="李四",
            credit_code="91510000MA6X12345X",
            registered_address="四川省成都市高新区天府大道北段128号",
            contact_phone="028-85123456",
            email="bidding@shinan-construction.com",
            bank_name="中国工商银行股份有限公司成都高新支行",
            bank_account="4402 2410 1910 0123 456"
        )
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
