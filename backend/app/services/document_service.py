import os
from loguru import logger
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.db.crud.document import document_crud

class DocumentService:
    def get_documents_list(self, db: Session):
        """处理获取所有历史记录的业务逻辑"""
        docs = document_crud.get_all_documents(db)
        docs_list = []
        for d in docs:
            docs_list.append({
                "id": d.id,
                "filename": d.filename,
                "status": d.parse_status,
                "created_at": d.created_at.isoformat() if hasattr(d, "created_at") and d.created_at else None
            })
        # 强制在 Python 层按 created_at 降序排
        docs_list.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return docs_list

    def get_document_result(self, db: Session, doc_id: str):
        """处理获取文档详情结果的业务逻辑（降级读取 Markdown 或 Chunk，拼装超大结果字典）"""
        doc_obj = document_crud.get_document_by_id(db, doc_id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="文档记录未找到")
            
        md_file_path = (
            doc_obj.parsed_metadata.get("md_file_path", "")
            if doc_obj and doc_obj.parsed_metadata
            else ""
        )
        
        doc_text = ""
        # 优先读取本地完整 Markdown，否则拼接 Chunk
        if md_file_path and os.path.exists(md_file_path):
            with open(md_file_path, "r", encoding="utf-8") as f:
                doc_text = f.read()
        else:
            chunks_for_display = document_crud.get_document_chunks(db, doc_id)
            doc_text = "\n\n".join([c.content for c in chunks_for_display]) if chunks_for_display else ""

        # 加载所有维度元数据
        metadata_objs = document_crud.get_all_metadata(db, doc_id)
        metadata_dict = {}
        for key, md_obj in metadata_objs.items():
            if md_obj:
                metadata_dict[key] = {k: v for k, v in md_obj.__dict__.items() if not k.startswith('_')}

        result = {
            "document_id": doc_id,
            "filename": doc_obj.filename,
            "extracted_text": doc_text,
            "qualifications_analysis": doc_obj.parsed_metadata.get("qualifications_analysis", {}) if doc_obj.parsed_metadata else {},
            "risks_analysis": doc_obj.parsed_metadata.get("risks_analysis", []) if doc_obj.parsed_metadata else [],
            "metadata": metadata_dict
        }
        
        return result

    def delete_document(self, db: Session, doc_id: str):
        """处理文档删除的业务逻辑（含数据库记录级联删除与本地文件物理清理）"""
        doc_obj = document_crud.get_document_by_id(db, doc_id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="文档记录未找到")
        
        # 记录待删除的物理路径
        file_path = doc_obj.file_path
        md_file_path = (doc_obj.parsed_metadata or {}).get("md_file_path", "")

        # 数据库级联删除
        try:
            document_crud.delete_document(db, doc_obj)
        except Exception as e:
            db.rollback()
            logger.error(f"级联删除文档 {doc_id} 的数据库记录失败: {e}")
            raise HTTPException(status_code=500, detail="删除数据库记录失败")

        # 尝试静默删除本地物理文件
        for path_to_delete in [file_path, md_file_path]:
            if path_to_delete and os.path.exists(path_to_delete):
                try:
                    os.remove(path_to_delete)
                    logger.info(f"成功清理本地残留文件: {path_to_delete}")
                except Exception as e:
                    logger.warning(f"未能彻底清理物理文件 {path_to_delete}: {e}")

document_service = DocumentService()
