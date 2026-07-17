import os
import sys
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.services.rag_service import rag_service
from app.services.metadata.engineering_service import engineering_service

logging.basicConfig(level=logging.INFO)

def test_engineering():
    print("正在准备测试 Engineering Extractor...")
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.parse_status == "completed").order_by(Document.created_at.desc()).first()
        if not doc:
            print("❌ 测试失败：数据库中没有找到已解析的文档。")
            return
            
        print(f"✅ 找到测试文档: {doc.filename} (ID: {doc.id})")
        
        search_keywords = "主要设备 规格 星号参数 标准 规范 样品 测试报告 CMA CNAS 现场施工难点 注意事项"
        print(f"🔍 正在使用 RAG 从数据库中检索相关上下文 (关键词: {search_keywords})...")
        
        context = rag_service.search_bidding_document(
            document_id=doc.id,
            query=search_keywords,
            top_k=3,
            section_title="项目需求",  # 强行限定仅在“项目需求”相关章节中检索
            context_mode="window",
            query_mode="split"
        )
        
        print("====== 检索到的上下文 ======")
        print(context)
        print("============================\n")
        
        print("🧠 正在调用大模型进行元数据提取（并真实落盘）...")
        result = engineering_service.extract_metadata(context=context, document_id=doc.id)
        
        print("\n================== 提取结果 ==================")
        if hasattr(result, "model_dump_json"):
            print(result.model_dump_json(indent=4))
        else:
            print(json.dumps(result.dict(), indent=4, ensure_ascii=False))
            
    finally:
        db.close()

if __name__ == "__main__":
    test_engineering()
