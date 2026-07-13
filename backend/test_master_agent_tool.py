import asyncio
import os
import sys

# 将 backend 根目录加入 sys.path，以支持正确的绝对导入
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.agents.supervisor import master_agent_node
from app.agents.state import BiddingState

def test_master_agent():
    print("==============================================")
    print("开始测试 Master Agent (自主 Tool Calling)")
    print("==============================================\n")
    
    db = SessionLocal()
    try:
        # 1. 从数据库中找一个刚刚解析完的文件 (取最新一条记录)
        doc = db.query(Document).filter(Document.parse_status == "completed").order_by(Document.created_at.desc()).first()
        
        if not doc:
            print("测试失败：数据库中没有找到状态为 'completed' 的已解析文档。")
            print("建议：请先去前端页面重新上传一次《招标.docx》进行解析，然后再运行此脚本。")
            return
            
        print(f"找到已解析文档！\n文件名: {doc.filename}\n文档ID: {doc.id}\n")
        
        # 2. 构造虚拟的 LangGraph State
        state: BiddingState = {
            "task_id": "test_local_task",
            "document_id": doc.id,
            "doc_text": "",
            "company_quals": "",
            "status": "RUNNING",
            "error": "",
            "qualifications_analysis": {},
            "risks_analysis": [],
            "cost_analysis": {}
        }
        
        # 3. 触发 Master Agent (这会触发大模型去查阅头部2.5万字，并自主调用搜索工具)
        print("Master Agent 正在思考，可能会调用 search_document_tool 进行向量检索，请稍候...\n")
        
        # 注意: 内部会有 logger 打印，您可以清晰看到大模型调用工具的过程
        result_state = master_agent_node(state)
        
        # 4. 打印最终结果
        if result_state.get("status") == "master_completed":
            print("\nMaster Agent 成功完成任务！")
            
            # 重新从数据库拉取，验证是否真的写入了 parsed_metadata
            db.refresh(doc)
            print("\n================== 最终输出的元数据 ==================")
            import json
            print(json.dumps(doc.parsed_metadata, indent=4, ensure_ascii=False))
            print("======================================================")
        else:
            print(f"\n执行失败，错误信息: {result_state.get('error')}")

    except Exception as e:
        print(f"\n测试脚本发生异常: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_master_agent()
