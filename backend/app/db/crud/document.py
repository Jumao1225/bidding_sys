from sqlalchemy.orm import Session
from app.db.models.project import Document, DocChunk
from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata, 
    EngineeringMetadata, EvaluationMetadata
)

class CRUDDocument:
    def get_all_documents(self, db: Session, user_id: str, tenant_id: str):
        """获取当前用户本租户下的所有文档记录并按ID倒序"""
        return db.query(Document).filter(
            Document.user_id == user_id, 
            Document.tenant_id == tenant_id
        ).order_by(Document.id.desc()).all()

    def get_document_by_id(self, db: Session, doc_id: str, user_id: str, tenant_id: str):
        """根据文档 ID 及权限获取单条记录"""
        return db.query(Document).filter(
            Document.id == doc_id,
            Document.user_id == user_id,
            Document.tenant_id == tenant_id
        ).first()

    def get_document_by_id_system(self, db: Session, doc_id: str):
        """系统内部使用，无视权限根据文档 ID 获取记录"""
        return db.query(Document).filter(Document.id == doc_id).first()

    def get_document_chunks(self, db: Session, doc_id: str):
        """获取文档的所有解析切片"""
        return db.query(DocChunk).filter(DocChunk.document_id == doc_id).order_by(DocChunk.chunk_index).all()

    def get_all_metadata(self, db: Session, doc_id: str):
        """一次性获取所有5大维度的业务 Metadata"""
        qual_md = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == doc_id).first()
        fin_md = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == doc_id).first()
        time_md = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == doc_id).first()
        eng_md = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == doc_id).first()
        eval_md = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == doc_id).first()
        
        return {
            "qualification": qual_md,
            "financial": fin_md,
            "timeline": time_md,
            "engineering": eng_md,
            "evaluation": eval_md
        }

    def delete_document(self, db: Session, doc_obj: Document):
        """级联删除指定文档对象及其所有下属结构"""
        db.delete(doc_obj)
        db.commit()

document_crud = CRUDDocument()
