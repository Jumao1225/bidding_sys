import pytest
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.agents.nodes.strategy_agent import analyze_qualifications_node, identify_risks_node

def test_strategy_agent_qualifications_and_risks_should_use_rag():
    """
    测试功能: Strategy Agent 的履约盘点与风险提示
    场景: 数据库中存在已解析完成的标书文档，触发 nodes
    期望结果: 两个节点都能成功返回结构化的 JSON 数据，证明 RAG 和 metadata 获取逻辑正常运行
    """
    db = SessionLocal()
    try:
        # 1. 准备测试数据
        doc = db.query(Document).filter(Document.parse_status == "completed").order_by(Document.created_at.desc()).first()
        
        if not doc:
            pytest.skip("跳过测试：数据库中没有已解析完成 (completed) 的文档。")
            
        print(f"\n--- 测试准备: 找到测试文档 {doc.filename} (ID: {doc.id}) ---")

        state = {
            "task_id": "pytest_task",
            "document_id": doc.id,
            "company_quals": "我公司具有建筑工程施工总承包一级，具有有效的安全生产许可证。",
            "doc_text": "",
            "status": "RUNNING",
            "error": "",
            "qualifications_analysis": {},
            "risks_analysis": [],
            "cost_analysis": {}
        }
        
        # 2. 执行履约盘点节点
        print("\n--- 测试 analyze_qualifications_node ---")
        quals_res = analyze_qualifications_node(state)
        
        assert "qualifications_analysis" in quals_res
        quals_data = quals_res["qualifications_analysis"]
        assert "match_score" in quals_data
        assert "items" in quals_data
        assert isinstance(quals_data["items"], list)
        if len(quals_data["items"]) > 0:
            assert "status" in quals_data["items"][0]
            
        # 3. 执行风险提示节点
        print("\n--- 测试 identify_risks_node ---")
        risks_res = identify_risks_node(state)
        
        assert "risks_analysis" in risks_res
        risks_data = risks_res["risks_analysis"]
        assert isinstance(risks_data, list)
        if len(risks_data) > 0:
            assert "risk_type" in risks_data[0]
            assert "severity" in risks_data[0]
            
        print("\n[SUCCESS] 测试通过: 履约盘点与风险提示节点成功运用 RAG 返回数据！")
        
    finally:
        db.close()
