import os
import sys
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.services.rag_service import rag_service
from app.services.metadata.financial_service import financial_service

logging.basicConfig(level=logging.INFO)

def test_financial():
    print("正在准备测试 Financial Extractor...")
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.parse_status == "completed").order_by(Document.created_at.desc()).first()
        if not doc:
            print("❌ 测试失败：数据库中没有找到已解析的文档。")
            return
            
        print(f"✅ 找到测试文档: {doc.filename} (ID: {doc.id})")
        
        search_keywords = "预算 限价 控制价 保证金 保函 预付款 结算 暂列金 暂估 单价限价"
        print(f"🔍 正在使用 RAG 从数据库中检索相关上下文 (关键词: {search_keywords})...")
        
        context = rag_service.search_bidding_document(
            document_id=doc.id,
            query=search_keywords,
            top_k=3,
            context_mode="window",
            query_mode="split"
        )
        
        print("====== 检索到的上下文 ======")
        print(context)
        print("============================\n")
        
        print("🧠 正在调用大模型进行元数据提取（并真实落盘）...")
        result = financial_service.extract_metadata(context=context, document_id=doc.id)
        
        print("\n================== 提取结果 ==================")
        if hasattr(result, "model_dump_json"):
            print(result.model_dump_json(indent=4))
        else:
            print(json.dumps(result.dict(), indent=4, ensure_ascii=False))
            
    finally:
        db.close()

if __name__ == "__main__":
    test_financial()
