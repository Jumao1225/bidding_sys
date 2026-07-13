import logging
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.project import DocChunk
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

class RAGService:
    def search_bidding_document(self, document_id: str, query: str, top_k: int = 5) -> str:
        """
        根据 query，在指定的 document_id 中进行向量检索。
        [高级优化版]: 支持 Query Expansion, Hybrid Search, 和 上下文滑窗。
        """
        logger.info(f"RAG Service 正在执行检索, 原始 query: {query}")
        
        try:
            # 1. 多路查询重写 (Query Expansion)
            expanded_queries = llm_service.expand_query(query, num_variants=3)
            logger.info(f"RAG Service 查询重写结果: {expanded_queries}")
            
            # 2. 生成多路向量
            query_embeddings = llm_service.generate_embeddings(expanded_queries)
            if not query_embeddings:
                return "检索失败：无法生成查询向量"
            
            db: Session = SessionLocal()
            try:
                hit_chunk_ids = set()
                
                # 预加载当前文档的所有 chunks 以便进行上下文滑窗 (按插入顺序近似取舍)
                all_chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).order_by(DocChunk.created_at, DocChunk.id).all()
                chunk_list = [c for c in all_chunks]
                chunk_id_to_idx = {c.id: idx for idx, c in enumerate(chunk_list)}
                
                # 3. 向量检索 (Vector Search)
                for q_vec in query_embeddings:
                    vector_hits = (
                        db.query(DocChunk)
                        .filter(DocChunk.document_id == document_id)
                        .order_by(DocChunk.embedding.cosine_distance(q_vec))
                        .limit(top_k)
                        .all()
                    )
                    for c in vector_hits:
                        hit_chunk_ids.add(c.id)
                        
                # 4. 混合检索 (Hybrid Search - ILIKE)
                for q_text in expanded_queries:
                    safe_q = q_text.replace('%', '\\%').replace('_', '\\_')
                    keyword_hits = (
                        db.query(DocChunk)
                        .filter(DocChunk.document_id == document_id, DocChunk.content.ilike(f"%{safe_q}%"))
                        .limit(top_k)
                        .all()
                    )
                    for c in keyword_hits:
                        hit_chunk_ids.add(c.id)
                        
                if not hit_chunk_ids:
                    return "未检索到相关内容。"
                
                # 5. 上下文滑窗 (Context Windowing: ±1)
                final_output_chunks = set()
                for cid in hit_chunk_ids:
                    idx = chunk_id_to_idx.get(cid)
                    if idx is not None:
                        # 加上前一个 chunk
                        if idx > 0:
                            final_output_chunks.add(chunk_list[idx - 1])
                        # 加上当前 chunk
                        final_output_chunks.add(chunk_list[idx])
                        # 加上后一个 chunk
                        if idx < len(chunk_list) - 1:
                            final_output_chunks.add(chunk_list[idx + 1])
                            
                # 6. 结果合并与去重排序
                sorted_results = sorted(list(final_output_chunks), key=lambda x: chunk_id_to_idx.get(x.id, 0))
                
                # 限制最终返回数量，避免大模型上下文爆掉 (最多返回 15 个 Chunk)
                max_return = 15
                sorted_results = sorted_results[:max_return]
                
                # 7. 提取结果并拼接 trace_info
                results = []
                for i, chunk in enumerate(sorted_results):
                    heading = "未知章节"
                    page_num = chunk.page_num if chunk.page_num else "未知"
                    
                    if chunk.trace_info:
                        if isinstance(chunk.trace_info, dict):
                            headings = chunk.trace_info.get("headings", [])
                            if headings:
                                heading = " > ".join(headings)
                    
                    text_block = f"【检索结果 {i+1}】(来源章节: {heading}, 第 {page_num} 页)\n内容: {chunk.content}"
                    results.append(text_block)
                
                final_result = "\n\n".join(results)
                logger.info(f"RAG 高级检索成功，综合召回 {len(sorted_results)} 个连贯片段。")
                return final_result
                
            finally:
                db.close()
                
        except Exception as e:
            logger.exception("RAG 检索异常")
            return f"检索发生异常: {str(e)}"

rag_service = RAGService()
