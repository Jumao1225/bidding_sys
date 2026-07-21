from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.core.context import current_user_id, current_tenant_id

def validate_document_access(document_id: str) -> bool:
    """
    通过读取上下文变量中的 user_id 和 tenant_id，
    校验当前请求是否拥有该 document_id 的访问权限。
    """
    user_id = current_user_id.get()
    tenant_id = current_tenant_id.get()
    
    # 如果上下文中没有用户状态，可能是非请求驱动的后台任务（如完全信任环境）
    # 但为了安全起见，如果在 Web 环境中缺少用户状态，应该默认拒绝
    if not user_id or not tenant_id:
        return False

    db: Session = SessionLocal()
    try:
        doc = document_crud.get_document_by_id(db, document_id, user_id, tenant_id)
        return doc is not None
    finally:
        db.close()
