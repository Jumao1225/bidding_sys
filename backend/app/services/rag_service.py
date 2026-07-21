import logging
import typing
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.project import DocChunk
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

def merge_overlapping_text(text1: str, text2: str, max_overlap: int = 400) -> str:
    """Find the longest suffix of text1 that matches a prefix of text2."""
    if not text1: return text2
    if not text2: return text1
    
    check_len = min(len(text1), len(text2), max_overlap)
    for i in range(check_len, 0, -1):
        suffix = text1[-i:]
        prefix = text2[:i]
        if suffix == prefix:
            return text1 + text2[i:]
    return text1 + "\n\n" + text2
class RAGService:
    def search_bidding_document(
        self,
        document_id: str,
        query: str,
        section_title: typing.Union[str, list] = None,
        top_k: int = 5,
        disable_expansion: bool = False,
        context_mode: str = "chapter",
        query_mode: str = "combined"
    ) -> str:
        """
        根据 query，在指定的 document_id 中进行向量检索与关键字混合检索。
        支持限定 section_title 章节检索与高精度重定向过滤。
        """
        logger.info(f"RAG Service 正在执行检索, 原始 query: {query}, 限定章节: {section_title}")
        
        try:
            # 安全类型转换防御：确保 top_k 为合法整数
            try:
                top_k_num = int(top_k) if top_k else 5
            except (ValueError, TypeError):
                top_k_num = 5

            # 1. 查询重写处理
            if query_mode == "split":
                # 按空格拆分出独立的查询词，去重并过滤空字符串
                expanded_queries = list(dict.fromkeys([q.strip() for q in query.split() if q.strip()]))
                if not expanded_queries:
                    expanded_queries = [query]
                logger.info(f"RAG Service 使用 split 模式，分词结果: {expanded_queries}")
            else:
                expanded_queries = [query]
                logger.info(f"RAG Service 使用 combined 模式，原始 query: {query}")
            
            # 2. 生成多路向量
            query_embeddings = llm_service.generate_embeddings(expanded_queries)
            if not query_embeddings:
                return "检索失败：无法生成查询向量"
            
            db: Session = SessionLocal()
            try:
                hit_chunk_ids = set()
                
                # 预加载当前文档的所有 chunks 以便进行上下文滑窗
                all_chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).order_by(DocChunk.chunk_index).all()
                chunk_list = [c for c in all_chunks]
                chunk_id_to_idx = {c.id: idx for idx, c in enumerate(chunk_list)}
                
                # 构建基准数据库 Query Filter，支持按 section_title 条件限定
                base_query = db.query(DocChunk).filter(DocChunk.document_id == document_id)
                if section_title:
                    if isinstance(section_title, str) and section_title.strip():
                        clean_sec = section_title.strip()
                        base_query = base_query.filter(DocChunk.section_title.ilike(f"%{clean_sec}%"))
                    elif isinstance(section_title, list) and section_title:
                        from sqlalchemy import or_
                        conditions = [DocChunk.section_title.ilike(f"%{sec.strip()}%") for sec in section_title if sec.strip()]
                        if conditions:
                            base_query = base_query.filter(or_(*conditions))

                # 3. 向量检索 (Vector Search)
                import math
                for q_vec in query_embeddings:
                    if any(math.isnan(x) for x in q_vec):
                        logger.error("🚨 致命错误: 本地 Embedding 模型生成了包含 NaN 的无效向量！已跳过本次向量检索，降级为关键字检索。请检查 bge-m3 模型或 PyTorch 环境。")
                        continue
                        
                    vector_hits = (
                        base_query
                        .order_by(DocChunk.embedding.cosine_distance(q_vec))
                        .limit(top_k_num)
                        .all()
                    )
                    for c in vector_hits:
                        hit_chunk_ids.add(c.id)
                        
                # 4. 混合检索 (Hybrid Search - ILIKE)
                for q_text in expanded_queries:
                    safe_q = q_text.replace('%', '\\%').replace('_', '\\_')
                    keyword_hits = (
                        base_query
                        .filter(DocChunk.content.ilike(f"%{safe_q}%"))
                        .limit(top_k_num)
                        .all()
                    )
                    for c in keyword_hits:
                        hit_chunk_ids.add(c.id)
                        
                if not hit_chunk_ids:
                    return "未检索到相关内容。"
                
                # 5. 基于章节的上下文补全 (Chapter-Based Context Retrieval) 或滑窗
                final_output_chunks = set()
                hit_section_titles = set()
                
                for cid in hit_chunk_ids:
                    idx = chunk_id_to_idx.get(cid)
                    if idx is not None:
                        chunk = chunk_list[idx]
                        
                        if context_mode == "window":
                            # 精细滑窗模式：只保留命中段落以及前后各一个段落 (±1)
                            final_output_chunks.add(chunk)
                            if idx > 0: final_output_chunks.add(chunk_list[idx - 1])
                            if idx < len(chunk_list) - 1: final_output_chunks.add(chunk_list[idx + 1])
                        else:
                            # 默认 chapter 模式：收集命中的正式章节
                            if chunk.section_title and chunk.section_title != "无章节/正文":
                                hit_section_titles.add(chunk.section_title)
                            else:
                                # 对于没有明确章节的段落，回退到物理滑窗 ±1
                                final_output_chunks.add(chunk)
                                if idx > 0: final_output_chunks.add(chunk_list[idx - 1])
                                if idx < len(chunk_list) - 1: final_output_chunks.add(chunk_list[idx + 1])
                            
                if context_mode != "window":
                    # 将命中章节内的**所有切片**完整拼入结果，实现“按章召回”
                    for chunk in chunk_list:
                        if chunk.section_title in hit_section_titles:
                            final_output_chunks.add(chunk)
                            
                # 6. 结果合并与去重排序
                sorted_results = sorted(list(final_output_chunks), key=lambda x: chunk_id_to_idx.get(x.id, 0))
                
                # 限制最终返回数量，避免大模型上下文爆掉 (最多返回 20 个 Chunk，约 6 万字)
                max_return = 20
                sorted_results = sorted_results[:max_return]
                
                # 7. 提取结果并拼接 trace_info，合并连续 Chunk 以消除重叠文本
                results = []
                current_merged_content = ""
                current_heading = "未知章节"
                current_page_num = "未知"
                last_idx = -2
                
                for i, chunk in enumerate(sorted_results):
                    idx = chunk_id_to_idx.get(chunk.id, -1)
                    
                    heading = "未知章节"
                    page_num = chunk.page_num if chunk.page_num else "未知"
                    
                    if chunk.trace_info:
                        if isinstance(chunk.trace_info, dict):
                            headings = chunk.trace_info.get("headings", [])
                            if headings:
                                heading = " > ".join(headings)
                    
                    if idx == last_idx + 1 and heading == current_heading:
                        # 连续的 chunk 且同属一个章节，进行去重叠合并
                        current_merged_content = merge_overlapping_text(current_merged_content, chunk.content)
                    else:
                        # 不连续或者跨章节了，保存上一个组
                        if current_merged_content:
                            text_block = f"【检索结果】(来源章节: {current_heading}, 第 {current_page_num} 页)\n内容: {current_merged_content}"
                            results.append(text_block)
                            
                        # 开启新的一组
                        current_merged_content = chunk.content
                        current_heading = heading
                        current_page_num = page_num
                        
                    last_idx = idx
                    
                if current_merged_content:
                    text_block = f"【检索结果】(来源章节: {current_heading}, 第 {current_page_num} 页)\n内容: {current_merged_content}"
                    results.append(text_block)
                
                # 更新序号
                for i, res in enumerate(results):
                    results[i] = res.replace("【检索结果】", f"【检索结果 {i+1}】")
                
                final_result = "\n\n".join(results)
                logger.info(f"RAG 高级检索成功，综合召回 {len(sorted_results)} 个连贯片段，合并去重叠后产生 {len(results)} 个连续块。")
                return final_result
                
            finally:
                db.close()
                
        except Exception as e:
            logger.exception("RAG 检索异常")
            return f"检索发生异常: {str(e)}"

    def get_rag_sources_for_citations(self, document_id: str, query: str, top_k: int = 5) -> list[dict]:
        """
        从数据库检索 RAG 结果，返回前端可展示的引文来源列表。
        每条包含 section_title 和 text_preview（前200字）。
        不同于 search_bidding_document 返回的拼接文本，此处保留各切片的元数据结构。
        """
        try:
            from app.db.session import SessionLocal
            from app.db.models.project import DocChunk
            
            # 生成查询向量
            query_embeddings = llm_service.generate_embeddings([query])
            if not query_embeddings:
                return []

            db: Session = SessionLocal()
            try:
                # 向量相似度检索，返回最相近的 top_k 条
                results = (
                    db.query(DocChunk)
                    .filter(DocChunk.document_id == document_id)
                    .order_by(DocChunk.embedding.cosine_distance(query_embeddings[0]))
                    .limit(top_k)
                    .all()
                )
                sources = []
                seen_sections: set[str] = set()
                for chunk in results:
                    sec = chunk.section_title or "未知章节"
                    # 同一章节只保留一条预览，避免重复展示
                    if sec not in seen_sections:
                        sources.append({
                            "section_title": sec,
                            "text_preview": chunk.content[:200] if chunk.content else ""
                        })
                        seen_sections.add(sec)
                return sources
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"获取 RAG 来源切片失败，降级返回空列表: {str(e)}")
            return []

rag_service = RAGService()
