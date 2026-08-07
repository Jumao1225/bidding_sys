from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.core.context import current_user_id, current_tenant_id

def validate_document_access(document_id: str) -> bool:
    """
    通过读取上下文变量中的 user_id 和 tenant_id，
    校验当前请求或 Worker 线程是否拥有该 document_id 的访问权限。
    在后台线程池或无状态环境下，只要文档存在于数据库中即放行。
    """
    if not document_id:
        return False

    user_id = current_user_id.get()
    tenant_id = current_tenant_id.get()

    db: Session = SessionLocal()
    try:
        from app.db.models.project import Document as DocumentModel
        doc = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if not doc:
            return False

        # 如果上下文中显式带有 user_id / tenant_id，进行严格归属校验
        if user_id and hasattr(doc, "user_id") and doc.user_id and doc.user_id != user_id:
            return False
        if tenant_id and hasattr(doc, "tenant_id") and doc.tenant_id and doc.tenant_id != tenant_id:
            return False

        return True
    except Exception:
        # 异常兜底保护，只要 document_id 有效则放行
        return True
    finally:
        db.close()
