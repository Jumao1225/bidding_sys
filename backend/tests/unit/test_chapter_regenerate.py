"""
单章节重新生成与 Prompt 微调功能单元测试 (test_chapter_regenerate.py)
"""
import os
import json
import tempfile
from unittest.mock import patch
from docx import Document
from types import SimpleNamespace

from app.schemas.bid_filler_schema import RegenerateChapterRequest, RegenerateChapterResponse
from app.agents.bid_filler_workers import (
    build_worker_prompt,
    _build_deterministic_pricing_proposal,
    _map_pricing_headers_to_fields,
)
from app.agents.bid_filler_agent import fill_docx_proposals_in_dom
from app.api.endpoints.bid_generator import (
    _restore_profile_slots_after_chapter_reset,
    _verify_pricing_table_writeback,
)


def test_regenerate_chapter_request_schema_validation():
    """验证单章节微调请求与响应模型结构与默认值。"""
    req = RegenerateChapterRequest(
        profile_id="profile-sichuan-shinan",
        chapter_title="商务条款响应及偏差表",
        custom_prompt="所有偏离项全部填无偏离，响应时间不超过1小时",
        category="needs_data",
        mapping_hint="deviation"
    )
    assert req.profile_id == "profile-sichuan-shinan"
    assert req.chapter_title == "商务条款响应及偏差表"
    assert "无偏离" in req.custom_prompt
    assert req.category == "needs_data"
    assert req.mapping_hint == "deviation"

    resp = RegenerateChapterResponse(
        document_id="doc_test_123",
        chapter_title="商务条款响应及偏差表",
        status="success",
        summary="已完成微调",
        proposals_count=3,
        execution_time_ms=1200,
        total_tokens=4500
    )
    assert resp.status == "success"
    assert resp.proposals_count == 3


def test_build_worker_prompt_with_custom_prompt_priority():
    """验证传入微调提示词时，Worker 提示词中能正确注入最高优先级指令。"""
    chapter_title = "技术要求响应及偏离表"
    custom_prompt = "特别声明提供 7x24 小时现场技术支持与应急备件库"

    system_prompt, user_prompt = build_worker_prompt(
        chapter_title=chapter_title,
        category="needs_data",
        template_text="模板原文要求",
        content_hint="填写说明",
        document_id="doc_test_123",
        docx_temp_path="",
        mapping_hint="deviation",
        extra_instructions=custom_prompt,
    )

    assert "【用户单章节专属重新生成与微调指令 — 最高优先级】" in system_prompt
    assert "7x24 小时现场技术支持" in system_prompt
    assert chapter_title in user_prompt


def test_regenerate_chapter_proposals_writeback_in_dom():
    """验证单章节微调生成的提案能精准刷入 Word DOM。"""
    doc = Document()
    doc.add_paragraph("商务条款响应：______")
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        doc.save(tmp_path)

    try:
        proposals = [
            {
                "path": "/body/p[1]",
                "proposed_text": "完全响应商务条款无偏离",
                "value": "完全响应商务条款无偏离",
                "type": "text"
            }
        ]

        count = fill_docx_proposals_in_dom(tmp_path, proposals)
        assert count > 0

        res_doc = Document(tmp_path)
        assert "完全响应商务条款无偏离" in res_doc.paragraphs[0].text
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_chapter_profile_restore_should_only_fill_reset_chapter_scope():
    """验证单章节重写的档案兜底只作用于当前章节，不污染其他章节。"""
    doc = Document()
    doc.add_paragraph("一、其他章节")
    doc.add_paragraph("地址：________________")
    doc.add_paragraph("二、资格证明文件")
    doc.add_paragraph("地址：________________")
    doc.add_paragraph("电话：________________")
    doc.add_paragraph("三、后续章节")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        doc.save(tmp_path)

    try:
        profile = SimpleNamespace(
            registered_address="档案地址",
            contact_phone="档案电话",
        )

        filled_count = _restore_profile_slots_after_chapter_reset(
            tmp_path,
            profile,
            None,
            "资格证明文件",
        )

        assert filled_count == 2
        result_doc = Document(tmp_path)
        assert result_doc.paragraphs[1].text == "地址：________________"
        assert result_doc.paragraphs[3].text == "地址： 档案地址"
        assert result_doc.paragraphs[4].text == "电话： 档案电话"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_pricing_opening_duplicate_path_proposals_should_keep_only_project_info():
    """验证报价章节同一路径重复提案不会拼接标题和旧占位符。"""
    doc = Document()
    doc.add_paragraph("五、投标配置及分项报价表")
    doc.add_paragraph("投标报价分析表")
    doc.add_paragraph("招标编号：号                                 项目名称：")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        doc.save(tmp_path)

    project_info = "招标编号：SZDZ-2026-NG008号 项目名称：和烁热能公司屋顶（400kW）分布式光伏发电项目"
    proposals = [
        {
            "path": "/body/p[3]",
            "proposed_text": f"投标报价分析表：{project_info}",
            "value": f"投标报价分析表：{project_info}",
            "type": "text",
        },
        {
            "path": "/body/p[3]",
            "proposed_text": project_info,
            "value": project_info,
            "type": "text",
        },
    ]

    try:
        count = fill_docx_proposals_in_dom(tmp_path, proposals)
        assert count > 0

        result_doc = Document(tmp_path)
        result_texts = [paragraph.text.strip() for paragraph in result_doc.paragraphs if paragraph.text.strip()]
        assert result_texts == ["五、投标配置及分项报价表", project_info]
        assert "投标报价分析表" not in "\n".join(result_texts)
        assert "号                                 项目名称" not in "\n".join(result_texts)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_build_worker_prompt_pricing_workflow_direct_matrix():
    """验证造价专家工作流使用抽象通用的 2D 矩阵直通指引，无具体数据硬编码。"""
    chapter_title = "投标配置及分项报价表"
    system_prompt, user_prompt = build_worker_prompt(
        chapter_title=chapter_title,
        category="needs_data",
        template_text="模板原文要求",
        content_hint="填写说明",
        document_id="doc_pricing_test_456",
        docx_temp_path="",
        mapping_hint="pricing",
    )

    # 1. 验证包含 2D 矩阵直通指引与字段说明
    assert "cost_estimates_json_matrix" in system_prompt
    assert "造价工程师与分项报价专家" in system_prompt
    assert "仅调用一次" in system_prompt
    assert "禁止查询纯文本报价字段" in system_prompt

    # 2. 验证防重复扫描规则
    assert "严禁重复盲目查询" in system_prompt or "严禁重复查询" in system_prompt

    # 3. 验证严禁硬编码具体设备与数据（杜绝具体锚定）
    for forbidden_word in ["光伏组件", "逆变器", "并网柜", "彩钢瓦", "2235211", "1634971"]:
        assert forbidden_word not in system_prompt


def test_map_pricing_headers_should_follow_runtime_table_columns():
    """验证报价表真实表头能转换为数据库矩阵字段，且不依赖固定列号。"""
    headers = ["序号", "标的物名称", "品牌、规格、型号", "生产厂家", "单位", "数量", "单价", "总价", "备注"]

    assert _map_pricing_headers_to_fields(headers) == [
        "__INDEX__",
        "item_name",
        "__BRAND_SPEC__",
        "manufacturer",
        "unit",
        "quantity",
        "unit_price",
        "calculated_total",
        "remark",
    ]


def test_deterministic_pricing_proposal_should_expand_table_and_preserve_footer():
    """正常场景：后端按真实表头生成完整矩阵，并把明细扩写到模板表尾之前。"""
    doc = Document()
    doc.add_paragraph("五、投标配置及分项报价表")
    doc.add_paragraph("投标报价分析表")
    table = doc.add_table(rows=4, cols=9)
    headers = ["序号", "标的物名称", "品牌、规格、型号", "生产厂家", "单位", "数量", "单价", "总价", "备注"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    table.rows[2].cells[0].text = "投标总报价："
    table.rows[2].cells[1].text = "大写：元"
    table.rows[3].cells[0].text = "交货期限："

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as file_handle:
        temp_path = file_handle.name

    matrix = [
        ["1", "项目A", "品牌A 规格A", "厂家A", "套", "1", "10.00", "10.00", ""],
        ["2", "项目B", "品牌B 规格B", "厂家B", "套", "2", "20.00", "40.00", ""],
    ]

    try:
        doc.save(temp_path)
        with patch(
            "app.agents.tools.bid_db_tools.query_financial_quotation_tool.func",
            return_value=json.dumps(matrix, ensure_ascii=False),
        ) as query_mock:
            proposal = _build_deterministic_pricing_proposal(
                document_id="doc-pricing-test",
                docx_path=temp_path,
                chapter_title="投标配置及分项报价表",
                prefetched_metadata={
                    "total_price_str": "50.00 元",
                    "total_price_words": "伍拾元整",
                    "delivery_period": "60日内完成",
                },
            )

        assert proposal is not None
        assert proposal["path"] == "/body/tbl[1]"
        proposal_matrix = json.loads(proposal["proposed_text"])
        assert proposal_matrix[:2] == matrix
        assert "50.00 元" in "".join(proposal_matrix[-2])
        assert "60日内完成" in "".join(proposal_matrix[-1])
        query_mock.assert_called_once()

        count = fill_docx_proposals_in_dom(temp_path, [proposal])
        assert count >= 4
        verified, verify_message = _verify_pricing_table_writeback(
            temp_path,
            "投标配置及分项报价表",
            [proposal],
        )
        assert verified, verify_message
        result_table = Document(temp_path).tables[0]
        assert len(result_table.rows) == 5
        assert result_table.rows[1].cells[1].text.strip() == "项目A"
        assert result_table.rows[2].cells[1].text.strip() == "项目B"
        assert "50.00 元" in "".join(cell.text for cell in result_table.rows[-2].cells)
        assert "60日内完成" in "".join(cell.text for cell in result_table.rows[-1].cells)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_fill_docx_proposals_in_dom_should_auto_redirect_when_path_shifted_to_title():
    """
    验证当绝对路径发生物理偏移命中固定标题时，写盘引擎能通用自愈重定向到真实槽位段落并成功写入。
    场景模拟：
    前面章节插入内容使得文档段落向后偏移 1 位：
    p[1]: 前置章节段落
    p[2]: 五、投标配置及分项报价表
    p[3]: 投标报价分析表 (固定标题，无槽位)
    p[4]: 招标编号：号                                 项目名称： (真实槽位)
    提案因模板基准给出的路径是 /body/p[3]（误打在子标题上）。
    期望：写盘引擎触发自愈纠偏，自动重定向到 /body/p[4]，成功写入招标编号与项目名称，且无漏填。
    """
    doc = Document()
    doc.add_paragraph("前置章节内容")
    doc.add_paragraph("五、投标配置及分项报价表")
    doc.add_paragraph("投标报价分析表")
    doc.add_paragraph("招标编号：号                                 项目名称：")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        doc.save(tmp_path)

    fake_project_code = "TEST-BID-2026-X01号"
    fake_project_name = "某某新能源分布式电站示范工程"
    proposal_text = f"招标编号：{fake_project_code}                                 项目名称：{fake_project_name}"

    proposals = [
        {
            "path": "/body/p[3]",  # 物理偏移导致路径打在 p[3]（标题行）
            "proposed_text": proposal_text,
            "value": proposal_text,
            "type": "text",
        }
    ]

    try:
        count = fill_docx_proposals_in_dom(tmp_path, proposals)
        assert count > 0

        res_doc = Document(tmp_path)
        all_texts = [p.text.strip() for p in res_doc.paragraphs if p.text.strip()]
        # 验证招标编号与项目名称被成功填入，没有被误拦截跳过
        assert any(fake_project_code in t and fake_project_name in t for t in all_texts)
        # 验证模板原有未填的空白占位已被替换
        assert "招标编号：号" not in "\n".join(all_texts)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
