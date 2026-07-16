import pytest
import sys
import os
import json

# 将 backend 根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.agents.supervisor import master_agent_node
from app.agents.state import BiddingState

def test_master_agent_tool_calling_should_extract_metadata_with_trace_info():
    """
    测试功能: Master Agent 的自主工具调用
    期望结果: 节点状态为 master_completed，且成功调用并落盘专项领域的 Metadata
    """
    db = SessionLocal()
    try:
        # 1. 准备测试数据 (取最新解析完的文档)
        doc = db.query(Document).filter(Document.parse_status == "completed").order_by(Document.created_at.desc()).first()
        
        # 确保环境中有可用的测试文档
        if not doc:
            pytest.skip("跳过测试：数据库中没有已解析完成 (completed) 的文档。")
            
        print(f"\n--- 测试准备: 找到测试文档 {doc.filename} (ID: {doc.id}) ---")

        # 2. 构造图节点的状态输入
        state: BiddingState = {
            "task_id": "pytest_task",
            "document_id": doc.id,
            "doc_text": "",
            "company_quals": "",
            "status": "RUNNING",
            "error": "",
            "qualifications_analysis": {},
            "risks_analysis": [],
            "cost_analysis": {}
        }
        
        # 3. 执行待测节点
        print("\n--- 正在执行 Master Agent 节点，请等待 LLM 思考与 Tool Calling... ---")
        result_state = master_agent_node(state)
        
        # 4. 断言 (Assertions)
        # 验证节点是否正常完成
        assert result_state.get("status") == "master_completed", f"节点执行失败: {result_state.get('error')}"
        
        from app.db.models.metadata import QualificationMetadata, TimelineMetadata
        
        qual_md = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == doc.id).first()
        time_md = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == doc.id).first()
        
        print("\n--- 验证专项提取工具是否落盘成功 ---")
        if qual_md:
            print(f"✅ QualificationMetadata 提取成功: {qual_md.industry_qualifications}")
        if time_md:
            print(f"✅ TimelineMetadata 提取成功: {time_md.project_id_code}")
            
        assert qual_md is not None or time_md is not None, "没有任何专项提取工具成功落盘数据，Tool Calling 可能失败"
            
    finally:
        db.close()
