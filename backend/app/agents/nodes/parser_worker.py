import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.services.extractor_service import extractor_service
from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk

logger = logging.getLogger(__name__)

def parser_worker_node(state: BiddingState) -> Dict[str, Any]:
    """
    文档解析流水线节点 (Parser Worker)
    负责从数据库加载文件记录，进行解析、切片，获取 Embedding 和溯源结构 (trace_info)，并存入 PostgreSQL。
    这是所有流程的第 0 步。
    """
    from app.worker.tasks import emit_agent_log
    logger.info("--- 启动 Parser Worker ---")
    emit_agent_log("info", "文档解析引擎已启动，准备执行物理层提取流程...")
    
    document_id = state.get("document_id")
    if not document_id:
        logger.error("State 中缺少 document_id，跳过 Parser Worker")
        return {"status": "parser_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        # 1. 查找文件记录
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            return {"status": "parser_failed", "error": f"未找到文档记录: {document_id}"}
            
        file_path = document.file_path
        logger.info(f"开始处理文档: {file_path}")

        # 如果文件状态已完成（通过文件哈希匹配复用），则直接跳过冗长的解析流程
        if document.parse_status == "completed":
            logger.info("文档已处于解析完成状态，直接复用切片与向量数据。")
            emit_agent_log("info", "检测到同名且同内容的文件缓存，已跳过 MinerU 解析，极速启动 Agent 智能体网络...")
            return {"status": "parser_completed"}

        # 2. 解析和切片（先解析，成功后再清理旧数据，避免解析失败导致数据全丢）
        import os
        filename = os.path.basename(file_path)
        emit_agent_log("info", f"正在调用底层智能解析引擎对 {filename} 进行物理层深度提取与多模态切割，过程可能需要 1-3 分钟，请耐心等待...")
        chunks = extractor_service.parse_and_chunk(file_path)
        logger.info(f"文档解析完成，共获得 {len(chunks)} 个切片。")
        emit_agent_log("success", f"文件解析完成！共切割出 {len(chunks)} 个高质量标准文本块。")

        if not chunks:
            return {"status": "parser_failed", "error": "文档解析未获得任何切片"}

        # 2.5. 解析成功后再清理旧切片数据（防重复，且在同一事务中）
        old_count = db.query(DocChunk).filter(DocChunk.document_id == document.id).delete()
        if old_count > 0:
            logger.info(f"已清理 {old_count} 条旧切片数据。")

        # 3. 提取 TOC (Table of Contents)
        toc_set = []
        for chunk in chunks:
            st = chunk.metadata.get("section_title")
            if st and st != "无章节/正文" and st not in toc_set:
                toc_set.append(st)
        
        toc_str = "\n".join([f"- {t}" for t in toc_set])
        logger.info(f"生成目录树 (TOC)，共 {len(toc_set)} 个顶级章节。")
        emit_agent_log("info", f"文档拓扑分析：目录树 (TOC) 提取成功，侦测到 {len(toc_set)} 个顶级章节导航。")
        
        if document.parsed_metadata is None:
            document.parsed_metadata = {}
        
        # 强制触发 SQLAlchemy JSON 列更新
        new_meta = dict(document.parsed_metadata)
        new_meta["table_of_contents"] = toc_str

        # 提取 output.md 原始落盘路径（由 extractor_service.parse_with_mineru 注入 metadata）
        # 存入 parsed_metadata 供 tasks.py 读取原始无切割全文，避免前端展示带 Overlap 重叠的 Chunk 拼接文本
        md_file_path = chunks[0].metadata.get("md_file_path", "") if chunks else ""
        if md_file_path:
            new_meta["md_file_path"] = md_file_path
            logger.info(f"output.md 路径已记录至 parsed_metadata: {md_file_path}")

        document.parsed_metadata = new_meta

        # 4. 获取 Embedding
        texts_to_embed = [chunk.page_content for chunk in chunks]
        logger.info("开始生成 Embedding 向量...")
        emit_agent_log("info", "正在调用 BGE-M3 混合检索大模型，开始为全部文本块生成多维稠密向量 (Embedding)...")
        embeddings = llm_service.generate_embeddings(texts_to_embed)
        logger.info("Embedding 生成完成。")
        emit_agent_log("success", "BGE-M3 向量化矩阵计算完成！准备执行 PostgreSQL (pgvector) 高维落盘写入...")

        # 4. 组装数据入库
        db_chunks = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            db_chunk = DocChunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                content=chunk.page_content,
                chunk_index=chunk.metadata.get("chunk_index", i),
                page_num=chunk.metadata.get("page_num"),
                section_title=chunk.metadata.get("section_title"),
                content_type=chunk.metadata.get("content_type"),
                trace_info=chunk.metadata.get("trace_info"),
                embedding=embedding,
            )
            db_chunks.append(db_chunk)

        # 批量保存切片
        db.add_all(db_chunks)
        
        # 更新原文档状态
        document.parse_status = "completed"
        
        db.commit()
        logger.info(f"成功将 {len(db_chunks)} 个带向量的切片存入 PostgreSQL。")
        emit_agent_log("success", f"结构化存储完毕！{len(db_chunks)} 个带向量切片已入库。即将唤醒 Master Agent 主控智能体...")
        
        # 贯彻 DB First 原则：仅返回状态，不向 State 塞入庞大的文本数据
        return {
            "status": "parser_completed"
        }
        
    except Exception as e:
        db.rollback()
        logger.exception("Parser Worker 执行失败")
        return {"status": "parser_failed", "error": str(e)}
    finally:
        db.close()
