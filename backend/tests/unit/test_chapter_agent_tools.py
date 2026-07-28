import pytest
import json
from app.agents.tools.chapter_agent_tools import (
    write_chapter_content,
    get_document_chapter_results,
    clear_document_chapter_results,
    search_chapter_requirements,
)
from app.agents.nodes.chapter_react_agent import (
    TOOL_REGISTRY,
    run_chapter_agent,
    build_chapter_agent_prompt,
)


def test_write_chapter_content_and_store_operations():
    """测试章节内容提交与结果内存池读写清理"""
    doc_id = "test_doc_123"
    clear_document_chapter_results(doc_id)

    # 1. 提交一个章节结果
    res_msg = write_chapter_content.invoke({
        "document_id": doc_id,
        "chapter_title": "一、投标函",
        "mapping_hint": "bid_letter",
        "filled_content": "致：某某买方\n我方承诺完全响应...",
        "table_rows_json": json.dumps([{"item": "设备A", "qty": 10}])
    })

    assert "成功" in res_msg

    # 2. 检查结果内存池
    stored = get_document_chapter_results(doc_id)
    assert len(stored) == 1
    key = "task_bid_letter_一、投标函"
    assert key in stored
    assert stored[key]["chapter_title"] == "一、投标函"
    assert stored[key]["filled_content"] == "致：某某买方\n我方承诺完全响应..."
    assert len(stored[key]["table_rows"]) == 1

    # 3. 清理内存池
    clear_document_chapter_results(doc_id)
    assert len(get_document_chapter_results(doc_id)) == 0


def test_tool_registry_tool_allocation():
    """测试不同 mapping_hint 映射标签的工具动态分配"""
    assert "bid_letter" in TOOL_REGISTRY
    assert "qualification" in TOOL_REGISTRY
    assert "pricing" in TOOL_REGISTRY
    assert "_unknown" in TOOL_REGISTRY

    qual_tools = [t.name for t in TOOL_REGISTRY["qualification"]]
    assert "query_company_qualifications" in qual_tools
    assert "write_chapter_content" in qual_tools

    pricing_tools = [t.name for t in TOOL_REGISTRY["pricing"]]
    assert "query_cost_estimation" in pricing_tools


def test_needs_writing_category_skips_agent_execution():
    """测试 needs_writing 分类直接生成占位符，不启动 LLM ReAct Agent"""
    doc_id = "test_doc_needs_writing"
    clear_document_chapter_results(doc_id)

    res = run_chapter_agent(
        document_id=doc_id,
        chapter_title="五、技术方案",
        chapter_number="五",
        mapping_hint="technical",
        category="needs_writing",
        content_hint="包含施工组织设计与设备配置"
    )

    assert res["status"] == "success"
    assert res["category"] == "needs_writing"

    stored = get_document_chapter_results(doc_id)
    assert len(stored) == 1
    key = "task_technical_五、技术方案"
    assert key in stored
    assert "[待人工补充：五、技术方案 的具体方案与证明材料]" in stored[key]["filled_content"]

    clear_document_chapter_results(doc_id)


def test_build_chapter_agent_prompt_structure():
    """测试 Prompt 模板生成结构"""
    prompt = build_chapter_agent_prompt(
        chapter_title="一、投标函",
        chapter_number="一",
        mapping_hint="bid_letter",
        category="needs_fill",
        template_text="致：____",
        content_hint="请如实填写",
        document_id="doc_xyz"
    )

    assert "一、投标函" in prompt
    assert "bid_letter" in prompt
    assert "needs_fill" in prompt
    assert "致：____" in prompt
    assert "write_chapter_content" in prompt
