from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import SessionLocal
from app.db.crud.qualification import qualification_crud
from app.schemas.qualification import QualificationResponse, QualificationCreate, QualificationUpdate
from app.services.company_qualification_service import company_qualification_service
from app.schemas.response.common import ResponseModel, success_response, error_response
from loguru import logger

router = APIRouter()

from app.api import deps
from app.db.models.user import User

@router.get("/", response_model=ResponseModel[List[QualificationResponse]])
def list_qualifications(
    db: Session = Depends(deps.get_db),
    tenant_id: str = Depends(deps.get_current_tenant)
):
    """获取租户的所有资质"""
    try:
        quals = qualification_crud.get_qualifications(db=db, tenant_id=tenant_id)
        return success_response(data=quals)
    except Exception as e:
        logger.error(f"Failed to list qualifications: {e}")
        raise HTTPException(status_code=500, detail="获取资质列表失败")

@router.post("/", response_model=ResponseModel[QualificationResponse])
def create_qualification(
    obj_in: QualificationCreate,
    db: Session = Depends(deps.get_db),
    tenant_id: str = Depends(deps.get_current_tenant),
    current_user: User = Depends(deps.get_current_active_user)
):
    """创建新的资质记录（保存前端确认的AI解析数据）"""
    try:
        db_obj = qualification_crud.create_qualification(db=db, obj_in=obj_in, tenant_id=tenant_id, user_id=current_user.id)
        return success_response(data=db_obj)
    except Exception as e:
        logger.error(f"Create qualification failed: {e}")
        raise HTTPException(status_code=500, detail="创建资质记录失败")

@router.post("/upload", response_model=ResponseModel[List[QualificationResponse]])
def upload_and_parse_qualification(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    tenant_id: str = Depends(deps.get_current_tenant)
):
    """上传文件并进行AI解析提取，自动创建资质记录（支持单文件多资质）"""
    try:
        new_quals = company_qualification_service.upload_and_parse(db=db, file=file, tenant_id=tenant_id)
        return success_response(data=new_quals)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload and parse qualification failed: {e}")
        raise HTTPException(status_code=500, detail="文件上传与解析失败")

@router.put("/{qual_id}", response_model=ResponseModel[QualificationResponse])
def update_qualification(
    qual_id: str,
    obj_in: QualificationUpdate,
    db: Session = Depends(deps.get_db),
    tenant_id: str = Depends(deps.get_current_tenant)
):
    """更新资质信息（主要用于用户手动修正AI解析结果）"""
    db_obj = qualification_crud.get_qualification_by_id(db=db, qual_id=qual_id, tenant_id=tenant_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="资质不存在")
    
    try:
        updated_qual = qualification_crud.update_qualification(db=db, db_obj=db_obj, obj_in=obj_in)
        return success_response(data=updated_qual)
    except Exception as e:
        logger.error(f"Update qualification failed: {e}")
        raise HTTPException(status_code=500, detail="更新资质信息失败")

@router.delete("/{qual_id}", response_model=ResponseModel[dict])
def delete_qualification(
    qual_id: str,
    db: Session = Depends(deps.get_db),
    tenant_id: str = Depends(deps.get_current_tenant)
):
    """删除资质"""
    db_obj = qualification_crud.get_qualification_by_id(db=db, qual_id=qual_id, tenant_id=tenant_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="资质不存在")
    
    try:
        qualification_crud.delete_qualification(db=db, db_obj=db_obj)
        return success_response(data={"id": qual_id}, message="删除成功")
    except Exception as e:
        logger.error(f"Delete qualification failed: {e}")
        raise HTTPException(status_code=500, detail="删除资质失败")
