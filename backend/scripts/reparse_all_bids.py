import sys
import os
from pathlib import Path

# 将 backend 根目录加入 sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from loguru import logger
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk
from app.services.extractor_service import extractor_service
from app.services.llm_service import llm_service

def reparse_every_single_document():
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        logger.info(f"🚀 [Reparse] 数据库中共计 {len(docs)} 个 Document 记录，全部执行全新强制冲洗重构...")

        for doc in docs:
            if not doc.file_path or not os.path.exists(doc.file_path):
                logger.warning(f"⚠️ 文件路径不存在: {doc.file_path} (doc_id={doc.id}), 跳过")
                continue

            logger.info(f"🔄 正在重构解析: {doc.filename} (doc_id={doc.id}, path={doc.file_path})...")

            # 1. 删除旧的腐败切块并立即提交，防止生成向量长时间闲置事务导致 PostgreSQL 掉线
            old_count = db.query(DocChunk).filter(DocChunk.document_id == doc.id).delete()
            db.commit()
            logger.info(f"   已清空 {old_count} 个旧数据 Chunk")

            # 2. 根据文件物理上传目录严格判断文档类型 (uploads/tenders -> tender 招标文件; uploads/bids or temp_uploads -> bid 投标文件)
            m_path = str(doc.file_path or "").replace("\\", "/").lower()
            pm = dict(doc.parsed_metadata or {})

            if "/tenders/" in m_path or "uploads/tenders" in m_path:
                target_doc_type = "tender"
                chunk_doc_type = "general"
            else:
                target_doc_type = "bid"
                chunk_doc_type = "bid"

            # 3. 调用最新切分逻辑重新 parse + chunk
            chunks = extractor_service.parse_and_chunk(doc.file_path, doc_type=chunk_doc_type)
            if not chunks:
                logger.error(f"❌ 解析未获得切片: {doc.filename}")
                continue

            # 4. 重新生成 Embeddings
            texts_to_embed = [c.page_content for c in chunks]
            embeddings = llm_service.generate_embeddings(texts_to_embed)

            # 5. 重新写入 doc_chunks 表
            db_chunks = []
            tenant_id = doc.tenant_id or "default_tenant"
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                sec_title = chunk.metadata.get("section_title") or chunk.metadata.get("chapter", "正文")
                db_chunk = DocChunk(
                    tenant_id=tenant_id,
                    user_id=doc.user_id,
                    document_id=doc.id,
                    chunk_index=i,
                    content=chunk.page_content,
                    content_type=chunk.metadata.get("content_type", "chapter_block"),
                    embedding=embedding,
                    section_title=sec_title,
                    trace_info=chunk.metadata.get("trace_info"),
                )
                db_chunks.append(db_chunk)

            db.add_all(db_chunks)
            doc.parse_status = "completed"
            doc.parsed_metadata = {**pm, "doc_type": target_doc_type}
            db.commit()
            logger.info(f"✅ 【{doc.filename}】(doc_id={doc.id}) 重构完成！全新插入 {len(db_chunks)} 个纯净切片。")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ 批量冲洗抛出异常: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reparse_every_single_document()
