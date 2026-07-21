from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.schemas.response.common import ResponseModel, success_response
from app.services.document_service import document_service
from app.db.models.user import User
from app.api import deps
from loguru import logger

router = APIRouter()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_model=ResponseModel[list[dict]])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """获取所有历史标书解析记录，按最新时间倒序"""
    try:
        docs_list = document_service.get_documents_list(db, current_user.id, current_user.tenant_id)
        return success_response(data=docs_list)
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(status_code=500, detail="获取历史记录失败")

@router.get("/{doc_id}/result", response_model=ResponseModel[dict])
def get_document_result(
    doc_id: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """根据文档 ID 恢复历史看板所需的完整 result 数据"""
    try:
        result = document_service.get_document_result(db, doc_id, current_user.id, current_user.tenant_id)
        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch document result {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="恢复历史看板数据失败")

@router.delete("/{doc_id}", response_model=ResponseModel[dict])
def delete_document(
    doc_id: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """删除指定的历史记录及其关联的所有解析数据"""
    try:
        document_service.delete_document(db, doc_id, current_user.id, current_user.tenant_id)
        return success_response(message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="删除记录失败")
