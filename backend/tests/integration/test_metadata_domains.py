import pytest
from app.services.metadata.qualification_service import qualification_service
from app.services.metadata.financial_service import financial_service
from app.services.metadata.timeline_service import timeline_service
from app.services.metadata.engineering_service import engineering_service
from app.services.metadata.evaluation_service import evaluation_service


@pytest.mark.asyncio
async def test_agent_tool_rag_flow():
    from app.db.session import SessionLocal
    from app.db.models.project import Document
    from app.agents.tools.metadata_tools import (
        extract_financial_info,
        extract_qualification_info,
        extract_timeline_info
    )
    
    # 1. 尝试从数据库里抓取一篇真实的、且切片表里确有数据的标书文档
    db = SessionLocal()
    try:
        from app.db.models.project import DocChunk
        # 先找一个确实有 Chunk 的 document_id
        chunk = db.query(DocChunk).first()
        if not chunk:
            pytest.skip("❌ 数据库 doc_chunks 表为空，请先在前端上传并解析文档。")
            
        document_id = str(chunk.document_id)
        doc = db.query(Document).filter(Document.id == document_id).first()
        
        print(f"\n✅ 找到真实文档进行全流程测试，Document ID: {document_id}")
        print(f"文件名: {doc.filename if doc else '未知'}")
        
        # 2. 模拟 Agent 调用“财务资金提取工具”
        print("\n=== 正在模拟 Agent 调用 extract_financial_info (RAG检索 + LLM提取) ===")
        # 直接测试一下 RAG 到底拿到了什么文本，方便排查
        from app.services.rag_service import rag_service
        from app.db.models.project import DocChunk
        chunk_count = db.query(DocChunk).filter(DocChunk.document_id == document_id).count()
        print(f"📦 当前文档在数据库中共有 {chunk_count} 个切片(Chunks)")
        
        raw_context = rag_service.search_bidding_document(
            document_id,
            "最高限价 预算 投标保证金 履约保证金 付款方式 支付比例",
            top_k=3,
            context_mode="window",
            query_mode="split"
        )
        print("🔍 RAG 实际检索到的上下文片段:")
        print("-" * 50)
        print(raw_context[:1000] + "\n...(截断)...")
        print("-" * 50)
        
        financial_result = extract_financial_info.invoke({
            "document_id": document_id,
            "search_keywords": "最高限价 预算 投标保证金 履约保证金 付款方式 支付比例"
        })
        
        assert "执行提取时发生错误" not in financial_result, f"工具执行报错: {financial_result}"
        print("💰 财务/资金提取结果 (LLM 返回):")
        print(financial_result)
        
        # 3. 模拟 Agent 调用“资质合规提取工具”
        print("\n=== 正在模拟 Agent 调用 extract_qualification_info (RAG检索 + LLM提取) ===")
        qual_keywords = "资质要求 证书 执业资格 历史业绩 同类项目"
        qual_raw_context = rag_service.search_bidding_document(
            document_id,
            qual_keywords,
            top_k=3,
            context_mode="window",
            query_mode="split"
        )
        print("🔍 资质要求 RAG 实际检索到的上下文片段:")
        print("-" * 50)
        print(qual_raw_context[:1000] + "\n...(截断)...")
        print("-" * 50)
        
        qual_result = extract_qualification_info.invoke({
            "document_id": document_id,
            "search_keywords": qual_keywords
        })
        
        assert "执行提取时发生错误" not in qual_result, f"工具执行报错: {qual_result}"
        print("📜 资质要求提取结果 (LLM 返回):")
        print(qual_result)
        
        # 4. 模拟 Agent 调用“商务时限提取工具”
        print("\n=== 正在模拟 Agent 调用 extract_timeline_info (RAG检索 + LLM提取) ===")
        timeline_keywords = "项目编号 投标截止时间 开标时间 答疑截止 工期 标书份数"
        timeline_raw_context = rag_service.search_bidding_document(
            document_id,
            timeline_keywords,
            top_k=3,
            context_mode="window",
            query_mode="split"
        )
        print("🔍 商务时限 RAG 实际检索到的上下文片段:")
        print("-" * 50)
        print(timeline_raw_context[:1000] + "\n...(截断)...")
        print("-" * 50)
        
        timeline_result = extract_timeline_info.invoke({
            "document_id": document_id,
            "search_keywords": timeline_keywords
        })
        
        assert "执行提取时发生错误" not in timeline_result, f"工具执行报错: {timeline_result}"
        print("⏳ 商务时限提取结果 (LLM 返回):")
        print(timeline_result)
        
    finally:
        db.close()
