from sqlalchemy.orm import Session
from app.db.models.project import Document, DocChunk
from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata, 
    EngineeringMetadata, EvaluationMetadata
)

class CRUDDocument:
    def get_all_documents(self, db: Session):
        """获取所有文档记录并按ID倒序（ID基于UUID创建顺序或时间顺序）"""
        return db.query(Document).order_by(Document.id.desc()).all()

    def get_document_by_id(self, db: Session, doc_id: str):
        """根据文档 ID 获取单条记录"""
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
