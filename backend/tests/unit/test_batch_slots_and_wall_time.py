"""
单元测试：批量槽位写盘工具与全流程物理耗时计算
"""
import pytest
import json
from app.agents.bid_filler_workers import _build_worker_tools


def test_batch_write_slots_tool_valid_json_should_collect_all_proposals():
    """测试 officecli_batch_write_slots 工具传入合法 JSON 数组时能够一次性收集全部提案"""
    collected = []
    tools = _build_worker_tools(docx_temp_path="", chapter_title="测试章节", collected_proposals=collected)
    
    batch_tool = next((t for t in tools if t.name == "officecli_batch_write_slots"), None)
    assert batch_tool is not None, "未找到 officecli_batch_write_slots 工具"

    sample_slots = [
        {"path": "/body/p[1]", "value": "2026年08月21日"},
        {"path": "/body/p[2]", "value": "某某科技有限公司"},
        {"path": "/body/p[3]", "value": "13800138000"}
    ]
    
    res = batch_tool.invoke({"slots_json_str": json.dumps(sample_slots, ensure_ascii=False)})
    assert "成功批量提交 3 个槽位的替换提案" in res
    assert len(collected) == 3
    assert collected[0]["path"] == "/body/p[1]"
    assert collected[0]["value"] == "2026年08月21日"
    assert collected[1]["path"] == "/body/p[2]"
    assert collected[2]["path"] == "/body/p[3]"


def test_batch_write_slots_tool_invalid_json_should_not_raise_exception():
    """测试 officecli_batch_write_slots 工具遇到畸形 JSON 时具备防御性容错能力"""
    collected = []
    tools = _build_worker_tools(docx_temp_path="", chapter_title="测试章节", collected_proposals=collected)
    batch_tool = next((t for t in tools if t.name == "officecli_batch_write_slots"), None)
    assert batch_tool is not None

    res = batch_tool.invoke({"slots_json_str": "invalid-json-string"})
    assert "成功批量提交 0 个槽位" in res
    assert len(collected) == 0


def test_tool_pruning_by_chapter_role_should_contain_only_specific_tools():
    """测试不同角色的 Worker 能够精准裁剪并装配其专属的轻量工具包"""
    # 1. 报价专家 (pricing) - 涵盖财务、BOM、槽位原位写入与企业元数据工具包
    pricing_tools = _build_worker_tools(docx_temp_path="", chapter_title="分项报价表", mapping_hint="pricing", category="needs_data")
    pricing_tool_names = [t.name for t in pricing_tools]
    assert "query_financial_quotation_tool" in pricing_tool_names
    assert "officecli_fill_table_rows" in pricing_tool_names
    assert "officecli_batch_write_slots" in pricing_tool_names
    assert "query_company_profile_tool" in pricing_tool_names
    assert "query_company_qualification_tool" not in pricing_tool_names  # 确认裁剪掉了资质工具
    assert "get_full_chapter_text" not in pricing_tool_names             # 确认裁剪掉了 RAG 工具
    assert len(pricing_tools) == 7

    # 2. 偏离表专家 (deviation)
    deviation_tools = _build_worker_tools(docx_temp_path="", chapter_title="商务条款偏离表", mapping_hint="deviation", category="needs_data")
    deviation_tool_names = [t.name for t in deviation_tools]
    assert "get_full_chapter_text" in deviation_tool_names
    assert "search_bidding_document" in deviation_tool_names
    assert "officecli_fill_table_rows" in deviation_tool_names
    assert "query_financial_quotation_tool" not in deviation_tool_names  # 确认裁剪掉了财务工具
    assert len(deviation_tools) == 4

    # 3. 公文表单专家 (letter / cover)
    letter_tools = _build_worker_tools(docx_temp_path="", chapter_title="投标函", mapping_hint="bid_letter", category="needs_fill")
    letter_tool_names = [t.name for t in letter_tools]
    assert "officecli_batch_write_slots" in letter_tool_names
    assert "query_company_profile_tool" in letter_tool_names
    assert "query_financial_quotation_tool" not in letter_tool_names
    assert "get_full_chapter_text" not in letter_tool_names
    assert len(letter_tools) == 6


def test_build_worker_prompt_selective_injection_should_only_inject_for_form_chapters():
    """测试基础企业档案与项目元数据仅定向注入公文表单类与报价类章节，绝不污染通用偏离表等章节"""
    from app.agents.bid_filler_workers import build_worker_prompt

    sample_metadata = {
        "company_name": "某某建设工程有限公司",
        "credit_code": "91510100MA6XXXXX12",
        "legal_person": "张某某",
        "project_name": "某标段施工总承包项目",
        "project_code": "SC-2026-001",
        "total_price_str": "1,234,567.00 元",
        "total_price_words": "人民币壹佰贰拾叁万肆仟伍佰陆拾柒元整",
    }

    # 1. 公文表单章节（投标函）：必须定向注入上述数据
    sys_prompt_1, user_prompt_1 = build_worker_prompt(
        chapter_title="投标函",
        category="needs_fill",
        template_text="致：______ 投标人：______",
        content_hint="",
        document_id="doc-123",
        mapping_hint="bid_letter",
        prefetched_metadata=sample_metadata
    )
    assert "【已定向提取的企业主档案与项目关键元数据 — 优先直接使用】" in user_prompt_1
    assert "某某建设工程有限公司" in user_prompt_1
    assert "91510100MA6XXXXX12" in user_prompt_1
    # 2. 商务偏离表章节（deviation）：100% 绝不注入企业基础档案，避免 Token 浪费
    sys_prompt_2, user_prompt_2 = build_worker_prompt(
        chapter_title="商务条款偏离表",
        category="needs_data",
        template_text="表格模板",
        content_hint="",
        document_id="doc-123",
        mapping_hint="deviation",
        prefetched_metadata=sample_metadata
    )
    assert "【已定向提取的企业主档案与项目关键元数据 — 优先直接使用】" not in user_prompt_2
    assert "某某建设工程有限公司" not in user_prompt_2

