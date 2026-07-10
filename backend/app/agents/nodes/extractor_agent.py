import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.services.extractor_service import extractor_service
from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk

logger = logging.getLogger(__name__)

def extractor_agent_node(state: BiddingState) -> Dict[str, Any]:
    """
    拆解智能体节点 (Extractor Agent)
    负责从数据库加载文件记录，进行解析、切片，获取 Embedding，并存入向量库。
    """
    logger.info("--- 启动 Extractor Agent ---")
    
    document_id = state.get("document_id")
    if not document_id:
        logger.error("State 中缺少 document_id，跳过 Extractor Agent")
        return {"status": "extractor_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        # 1. 查找文件记录
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            return {"status": "extractor_failed", "error": f"未找到文档记录: {document_id}"}
            
        file_path = document.file_path
        logger.info(f"开始处理文档: {file_path}")

        # 2. 解析和切片
        chunks = extractor_service.parse_and_chunk(file_path)
        logger.info(f"文档解析完成，共获得 {len(chunks)} 个切片。")

        if not chunks:
            return {"status": "extractor_failed", "error": "文档解析未获得任何切片"}

        # 3. 获取 Embedding
        texts_to_embed = [chunk.page_content for chunk in chunks]
        logger.info("开始生成 Embedding 向量...")
        embeddings = llm_service.generate_embeddings(texts_to_embed)
        logger.info("Embedding 生成完成。")

        # 4. 组装数据入库
        db_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            db_chunk = DocChunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                content=chunk.page_content,
                page_num=chunk.metadata.get("page_num"),
                section_title=chunk.metadata.get("section_title"),
                content_type=chunk.metadata.get("content_type"),
                embedding=embedding
            )
            db_chunks.append(db_chunk)

        # 批量保存切片
        db.add_all(db_chunks)
        
        # 更新原文档状态
        document.parse_status = "completed"
        
        db.commit()
        logger.info(f"成功将 {len(db_chunks)} 个带向量的切片存入 PostgreSQL。")
        
        # 将解析出的全文也更新到 state 中，供后续简单的非RAG节点（如需要）使用
        full_text = "\n\n".join(texts_to_embed)
        
        return {
            "status": "extractor_completed",
            "doc_text": full_text
        }
        
    except Exception as e:
        db.rollback()
        logger.exception("Extractor Agent 执行失败")
        return {"status": "extractor_failed", "error": str(e)}
    finally:
        db.close()
