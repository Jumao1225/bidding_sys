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
    场景: 数据库中存在已解析完成的标书文档，触发 Master Agent 节点
    期望结果: 节点状态为 master_completed，且提取的 pain_points 中包含结构化溯源信息 (来源章节/页码)
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
        
        # 刷新数据库对象，验证结果是否落库
        db.refresh(doc)
        parsed_metadata = doc.parsed_metadata
        
        print("\n--- 大模型提取的落库结果 ---")
        print(json.dumps(parsed_metadata, indent=4, ensure_ascii=False))
        
        # 验证核心字段是否存在
        assert "project_number" in parsed_metadata
        assert "budget_limit" in parsed_metadata
        assert "hard_qualifications" in parsed_metadata
        assert "pain_points" in parsed_metadata
        
        # 核心验证: pain_points 必须是数组，并且通过 RAG Tool 获取了溯源信息
        pain_points = parsed_metadata["pain_points"]
        assert isinstance(pain_points, list), "pain_points 应该是一个数组"
        
        # 如果 pain_points 不为空，验证其元素是否包含了溯源后缀
        if pain_points:
            has_trace_info = any("来源" in pt or "页" in pt for pt in pain_points)
            assert has_trace_info, f"痛点描述中缺少结构化溯源标记。实际结果: {pain_points}"
            print("\n✅ 测试通过: 成功在痛点描述中发现了 RAG 结构化溯源标记！")
            
    finally:
        db.close()
