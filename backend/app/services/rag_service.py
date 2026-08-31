import logging
import re
import typing
import unicodedata
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.project import DocChunk
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


def _normalize_section_title(value: object) -> str:
    """统一章节标题格式，用于数据库字段的精确语义比对。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"^[#*`~\s　]+", "", normalized)
    return re.sub(r"[\s　]+", "", normalized).strip()


def _section_title_stem(value: object) -> str:
    """去除章节序号前缀，保留局部标题正文用于精确语义比对。"""
    stem = _normalize_section_title(value)
    prefix_pattern = r"^(?:第[一二三四五六七八九十百零\d]+[章节部分篇]|[一二三四五六七八九十百零\d]+[、.])"
    while True:
        stripped = re.sub(prefix_pattern, "", stem, count=1)
        if stripped == stem:
            return stem
        stem = stripped


def _resolve_exact_section_titles(
    db: Session,
    document_id: str,
    section_title: typing.Union[str, list],
    tenant_id: typing.Optional[str] = None,
) -> list[str]:
    """从当前文档的 section_title 字段中解析精确匹配值，拒绝宽泛子串匹配。"""
    requested_titles = section_title if isinstance(section_title, list) else [section_title]
    requested_norms = {
        title_key
        for title in requested_titles
        for title_key in {
            _normalize_section_title(title),
            _section_title_stem(title),
        }
        if title_key
    }
    if not requested_norms:
        return []

    query = db.query(DocChunk.section_title).filter(
        DocChunk.document_id == document_id,
        DocChunk.section_title.isnot(None),
    )
    if tenant_id:
        query = query.filter(DocChunk.tenant_id == tenant_id)

    matched_titles: list[str] = []
    seen_titles: set[str] = set()
    for (stored_title,) in query.distinct().all():
        stored_keys = {
            _normalize_section_title(stored_title),
            _section_title_stem(stored_title),
        }
        if stored_keys.intersection(requested_norms) and stored_title not in seen_titles:
            matched_titles.append(stored_title)
            seen_titles.add(stored_title)
    return matched_titles

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
        query_mode: str = "combined",
        tenant_id: typing.Optional[str] = None,
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
                document_filter = [DocChunk.document_id == document_id]
                if tenant_id:
                    document_filter.append(DocChunk.tenant_id == tenant_id)

                all_chunks = db.query(DocChunk).filter(*document_filter).order_by(DocChunk.chunk_index).all()
                chunk_list = [c for c in all_chunks]
                chunk_id_to_idx = {c.id: idx for idx, c in enumerate(chunk_list)}
                
                # 构建基准数据库 Query Filter，支持按 section_title 条件限定（剔除 0 号目录页与 toc_block）
                section_filter_fallback = False
                base_query = db.query(DocChunk).filter(
                    DocChunk.document_id == document_id,
                    DocChunk.chunk_index > 0,
                    DocChunk.content_type != "toc_block"
                )
                if tenant_id:
                    base_query = base_query.filter(DocChunk.tenant_id == tenant_id)
                if section_title:
                    # 章节限定只允许命中数据库中完整相同的 section_title，
                    # 避免“项目需求”误命中“项目需求响应表”等相似模板标题。
                    exact_section_titles = _resolve_exact_section_titles(
                        db,
                        document_id,
                        section_title,
                        tenant_id=tenant_id,
                    )
                    if exact_section_titles:
                        base_query = base_query.filter(
                            DocChunk.section_title.in_(exact_section_titles)
                        )
                    else:
                        section_filter_fallback = True
                        logger.warning(
                            "RAG 章节限定未找到精确 section_title，降级为当前文档向量召回：文档ID=%s，章节=%s",
                            document_id,
                            section_title,
                        )

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
                # 当章节限定在旧数据中没有精确 section_title 时，优先相信向量命中，
                # 避免“项目需求”等泛关键词把响应模板加入目标章节上下文。
                if not section_filter_fallback or not hit_chunk_ids:
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
                elif section_filter_fallback:
                    logger.info(
                        "RAG 章节限定降级时保留向量命中，跳过泛关键词扩散：文档ID=%s，命中分块=%d",
                        document_id,
                        len(hit_chunk_ids),
                    )
                        
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
                                # 对于没有明确章节的段落，回退到物理滑窗 ±1（严格排除 0 号目录页干扰）
                                if chunk.chunk_index > 0:
                                    final_output_chunks.add(chunk)
                                if idx > 1:
                                    final_output_chunks.add(chunk_list[idx - 1])
                                if idx < len(chunk_list) - 1:
                                    final_output_chunks.add(chunk_list[idx + 1])
                            
                if context_mode != "window":
                    # 将命中章节内的**所有切片**完整拼入结果，实现“按章召回”
                    for chunk in chunk_list:
                        if chunk.section_title in hit_section_titles:
                            final_output_chunks.add(chunk)
                            
                # 6. 结果合并与去重排序
                sorted_results = sorted(list(final_output_chunks), key=lambda x: chunk_id_to_idx.get(x.id, 0))
                
                # chapter 模式必须返回命中 section_title 的全部分块；window 模式才保留安全上限。
                if context_mode == "window":
                    sorted_results = sorted_results[:20]
                
                # 7. 提取结果并拼接 trace_info，合并连续 Chunk 以消除重叠文本
                results = []
                current_merged_content = ""
                current_heading = "正文"
                current_page_num = "未知"
                last_idx = -2
                
                for i, chunk in enumerate(sorted_results):
                    idx = chunk_id_to_idx.get(chunk.id, -1)
                    
                    heading = chunk.section_title or "正文"
                    page_num = chunk.page_num if chunk.page_num is not None else "未知"
                    
                    if chunk.trace_info and isinstance(chunk.trace_info, dict):
                        headings = chunk.trace_info.get("headings") or chunk.trace_info.get("hierarchy")
                        if headings:
                            heading = " > ".join(headings)
                        elif chunk.trace_info.get("section_path"):
                            heading = chunk.trace_info.get("section_path")
                    
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

    def get_full_chapter_text(self, document_id: str, chapter_name: str) -> str:
        """
        获取指定文档中某个章节的 100% 连贯全文原文（无 Top-K 向量截断）。
        在数据库中按 section_title 精确匹配并按 DocChunk.chunk_index 顺序拼接所有相关切片。
        允许章节序号存在差异，但不使用任意子串模糊匹配，避免误取响应表或格式模板。
        """
        if not document_id or not chapter_name:
            return "错误：必须提供 document_id 和 chapter_name"

        clean_name = chapter_name.strip()
        db: Session = SessionLocal()
        try:
            matched_titles = _resolve_exact_section_titles(db, document_id, clean_name)
            if not matched_titles:
                logger.info(
                    "RAGService: section_title 精确匹配不到章节 '%s'（文档ID: %s）",
                    clean_name,
                    document_id,
                )
                return f"未能在文档中检索到章节名称匹配 '{chapter_name}' 的任何段落。"

            chunks = (
                db.query(DocChunk)
                .filter(
                    DocChunk.document_id == document_id,
                    DocChunk.section_title.in_(matched_titles),
                )
                .order_by(DocChunk.chunk_index)
                .all()
            )

            if not chunks:
                logger.info(
                    "RAGService: section_title 已解析但没有可用分块：章节=%s，文档ID=%s",
                    clean_name,
                    document_id,
                )
                return f"未能在文档中检索到章节名称匹配 '{chapter_name}' 的任何段落。"

            matched_sections = list(dict.fromkeys([c.section_title for c in chunks if c.section_title]))
            content_blocks = [c.content for c in chunks if c.content]
            merged_content = "\n\n".join(content_blocks)

            hdr = f"=== 章节【{', '.join(matched_sections)}】完整原文 (共 {len(chunks)} 个段落) ===\n\n"
            return hdr + merged_content
        except Exception as e:
            logger.exception(f"获取整章原文发生异常 ({chapter_name}): {e}")
            return f"获取整章原文发生异常: {str(e)}"
        finally:
            db.close()


rag_service = RAGService()
