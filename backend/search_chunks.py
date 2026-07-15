import argparse
from app.db.session import SessionLocal
from app.db.models.project import DocChunk, Document
from app.services.llm_service import llm_service

def search(keyword: str, limit: int = 5, disable_expansion: bool = False):
    db = SessionLocal()
    try:
        print(f"\n🧠 原始搜索词: '{keyword}'")
        
        # 1. 多路查询重写 (Query Expansion)
        if disable_expansion:
            expanded_queries = [keyword]
            print("🛑 已开启严格模式，跳过查询重写。")
        else:
            print("🔄 正在使用 LLM 进行多路查询重写 (Query Expansion)...")
            expanded_queries = llm_service.expand_query(keyword, num_variants=3)
            print(f"   => 重写结果: {expanded_queries}")
            
        print("\n🧠 正在生成查询向量...")
        query_embeddings = llm_service.generate_embeddings(expanded_queries)
        if not query_embeddings:
            print("❌ 向量生成失败！")
            return
            
        print("🔍 正在执行混合检索 (Hybrid Search: PgVector + ILIKE)...")
        hit_chunk_ids = set()
        
        # 2. 向量检索 (Vector Search)
        for q_vec in query_embeddings:
            vector_hits = db.query(DocChunk.id).order_by(DocChunk.embedding.cosine_distance(q_vec)).limit(limit).all()
            for (cid,) in vector_hits:
                hit_chunk_ids.add(cid)
                
        # 3. 关键字检索 (ILIKE Search)
        for q_text in expanded_queries:
            safe_q = q_text.replace('%', '\\%').replace('_', '\\_')
            keyword_hits = db.query(DocChunk.id).filter(DocChunk.content.ilike(f"%{safe_q}%")).limit(limit).all()
            for (cid,) in keyword_hits:
                hit_chunk_ids.add(cid)
                
        if not hit_chunk_ids:
            print("未找到包含该关键词的切片。")
            return
            
        # 获取所有命中的 chunks，以提取它们所属的文档和章节
        hit_chunks = db.query(DocChunk).filter(DocChunk.id.in_(hit_chunk_ids)).all()
        
        # 4. 基于章节的上下文补全 (Chapter-Based Context Retrieval)
        doc_sections = set()
        for c in hit_chunks:
            if c.section_title and c.section_title != "无章节/正文":
                doc_sections.add((c.document_id, c.section_title))
            else:
                # 针对无章节的孤立文本，我们暂时使用它自己作为 fallback
                doc_sections.add((c.document_id, "无章节孤立文本"))

        print(f"\n📊 混合检索命中！共波及 {len(doc_sections)} 个完整章节上下文:")
        print("="*60)
        
        for doc_id, section in doc_sections:
            # 顺便查询一下文档的真实文件名，方便人类阅读
            doc_record = db.query(Document).filter(Document.id == doc_id).first()
            doc_name = doc_record.filename if doc_record else doc_id
            
            if section == "无章节孤立文本":
                # 退化处理：仅展示命中的无章节切片
                chapter_chunks = [c for c in hit_chunks if c.document_id == doc_id and (not c.section_title or c.section_title == "无章节/正文")]
            else:
                # 核心逻辑：去数据库把同一个文档、同一个章节的所有切片全部按时间顺序拉出来拼好！
                chapter_chunks = db.query(DocChunk).filter(
                    DocChunk.document_id == doc_id,
                    DocChunk.section_title == section
                ).order_by(DocChunk.chunk_index).all()
            
            full_text = "\n\n".join([c.content for c in chapter_chunks])
            
            print(f"📚 所属文档: {doc_name} (ID: {doc_id})")
            print(f"    完整章节: {section} (共组装 {len(chapter_chunks)} 个切片)")
            print(f"    完整上下文:\n{full_text}")
            print("*" * 80)
            
    except Exception as e:
        print(f"❌ 搜索时发生错误: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="高级混合检索测试工具 (100% 匹配后端 RAG 策略)")
    parser.add_argument("keyword", type=str, help="要搜索的关键词")
    parser.add_argument("--limit", type=int, default=5, help="单路检索的限制条数 (默认 5)")
    parser.add_argument("--strict", action="store_true", help="严格模式：关闭 LLM 词义重写发散")
    
    args = parser.parse_args()
    search(args.keyword, args.limit, args.strict)
