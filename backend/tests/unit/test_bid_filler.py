"""
BidFiller Agent & BidFormatFillerService 单元测试

测试大写金额转化、Agent Tool Calling 查库、下划线继承写 Word 功能。
"""

import pytest
import io
from docx import Document
from app.utils.rmb_formatter import number_to_chinese_rmb
from app.agents.bid_filler_agent import bid_filler_agent
from app.schemas.bid_filler_schema import CompanyProfile
from app.services.bid_format_filler_service import bid_format_filler_service


def test_number_to_chinese_rmb_should_convert_correctly():
    """测试数字转换为人民币大写汉字算法"""
    assert number_to_chinese_rmb(967840.36) == "玖拾陆万柒仟捌佰肆拾元叁角陆分"
    assert number_to_chinese_rmb(20000.00) == "贰万元整"
    assert number_to_chinese_rmb(100.50) == "壹佰元伍角"
    assert number_to_chinese_rmb(0.0) == "零元整"


def test_bid_format_filler_service_underline_inheritance():
    """测试下划线继承逻辑：原处有下划线则保留 underline=True，原处无下划线则不添加"""
    doc = Document()
    
    # 构造原处带下划线的段落
    p1 = doc.add_paragraph()
    r1 = p1.add_run("投标人名称：________")
    r1.underline = True

    # 构造原处不带下划线的段落
    p2 = doc.add_paragraph()
    p2.add_run("项目名称：[项目名称]")

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    template_bytes = output.getvalue()

    # 1. 扫描待填位置
    placeholders = bid_format_filler_service.scan_detected_placeholders(template_bytes)
    assert len(placeholders) >= 1

    # 2. 模拟替换
    replacement_map = {
        "投标人名称：________": "投标人名称：四川石楠建设工程有限公司",
        "[项目名称]": "湖南省烟草公司衡阳市公司关于现代终端建设项目"
    }

    filled_bytes = bid_format_filler_service.fill_docx_with_audit_trail(
        docx_bytes=template_bytes,
        replacement_map=replacement_map,
        audit_items=[]
    )

    assert filled_bytes is not None
    res_doc = Document(io.BytesIO(filled_bytes))
    
    # 验证含有“四川石楠建设工程有限公司”的 Run 带有下划线
    target_p = [p for p in res_doc.paragraphs if "四川石楠建设工程有限公司" in p.text][0]
    assert target_p is not None
    val_run = [r for r in target_p.runs if "四川石楠建设工程有限公司" in r.text][0]
    assert val_run.underline is True or 'w:u' in val_run._element.xml


def test_scan_node_temp_path_should_be_in_backend_dir():
    """测试 scan_node 的工作副本路径是否精准定位在 backend 目录下的 uploads/drafts 中"""
    import os
    from app.agents.bid_filler_agent import scan_node

    doc_bytes = io.BytesIO()
    Document().save(doc_bytes)
    state = {
        "document_id": "test_doc_12345678",
        "original_docx": doc_bytes.getvalue(),
        "original_context": "",
        "slot_analysis": None,
        "worker_proposals": None,
        "db_session": None,
        "company_profile": None,
        "docx_temp_path": None,
        "audit_items": [],
        "audit_report": None,
        "filled_docx_bytes": None,
    }
    res = scan_node(state)
    temp_path = res.get("docx_temp_path")
    assert temp_path is not None
    # 判断生成的绝对路径中必定包含 backend
    assert "backend" in os.path.normcase(temp_path)
    assert os.path.exists(temp_path)
    # 测试结束后清理测试文件
    try:
        os.remove(temp_path)
    except Exception:
        pass


def test_proposals_to_commands_should_handle_none_source_and_wrap_tc():
    """测试 proposals_to_commands 是否能够放行 source_tool 为 none/空 的合规提案，并且为表格单元格 /tc[N] 自动补正段落路径 /p[1]"""
    from app.agents.bid_filler_agent import proposals_to_commands

    mock_proposals = [
        # 场景1：source_tool 为 none 或空，但内容合法（如大写金额或自主核算总价），应当放行
        {"source_tool": "none", "path": "/body/p[2]/r[1]", "proposed_text": "玖拾陆万柒仟捌佰肆拾元叁角陆分"},
        {"source_tool": "", "path": "/body/p[3]/r[1]", "proposed_text": "四川某某实业有限公司"},
        # 场景2：表格单元格 XPath /body/tbl[1]/tr[2]/tc[2] 止步于单元格，应自动吸附 /p[1]
        {"source_tool": "query_project_metadata_tool", "path": "/body/tbl[1]/tr[2]/tc[2]", "proposed_text": "15.00万元"},
        # 场景3：携带 OfficeCLI 自带属性的定位路径 /body/p[@paraId=17F154A1]/r[1]，严禁一刀切误拦
        {"source_tool": "query_company_qualification_tool", "path": "/body/p[@paraId=17F154A1]/r[1]", "proposed_text": "电力工程施工总承包二级"},
        # 场景4：占位异常描述，应当过滤
        {"source_tool": "db", "path": "/body/p[4]/r[1]", "proposed_text": "[待补充资质要求]"},
    ]

    cmds, approved, rejected = proposals_to_commands(mock_proposals)
    assert approved == 4
    assert rejected == 1
    assert len(cmds) == 4
    # 断言场景2成功转化为段落路径
    table_cmd = [c for c in cmds if "tbl[1]" in c["path"]][0]
    assert table_cmd["path"] == "/body/tbl[1]/tr[2]/tc[2]/p[1]"
    # 断言场景3原生保持并获悉打进命令集
    para_cmd = [c for c in cmds if "@paraId" in c["path"]][0]
    assert para_cmd["props"]["text"] == "电力工程施工总承包二级"


def test_proposals_to_commands_should_preserve_label_prefix():
    """测试 proposals_to_commands 在提案未携带标签前缀时，能依据 original_context 自动保留并补全字段前缀"""
    from app.agents.bid_filler_agent import proposals_to_commands, _extract_label_prefix

    # 1. 验证 _extract_label_prefix 提炼能力
    assert _extract_label_prefix("投标人名称（单位盖章）：__________________________") == "投标人名称（单位盖章）："
    assert _extract_label_prefix("地    址：__________________________") == "地    址："
    assert _extract_label_prefix("项目编号：[项目编号]") == "项目编号："

    # 2. 验证 proposals_to_commands 前缀自动防护
    mock_proposals = [
        {
            "source_tool": "query_company_profile_tool",
            "path": "/body/p[12]",
            "original_context": "投标人名称（单位盖章）：__________________________",
            "proposed_text": "北京某某科技有限公司",
        },
        {
            "source_tool": "query_company_profile_tool",
            "path": "/body/p[13]",
            "original_context": "地    址：__________________________",
            "proposed_text": "地    址：北京市海淀区中关村南大街1号",
        },
        {
            "source_tool": "query_financial_quotation_tool",
            "path": "/body/tbl[1]/tr[2]/tc[2]",
            "original_context": "表格第 1 个表，第 2 行，第 2 列：",
            "proposed_text": "15.00万元",
        }
    ]

    cmds, approved, rejected = proposals_to_commands(mock_proposals)
    assert approved == 3
    assert cmds[0]["props"]["text"] == "投标人名称（单位盖章）：北京某某科技有限公司"
    # 已自带前缀的不重复拼接
    assert cmds[1]["props"]["text"] == "地    址：北京市海淀区中关村南大街1号"
    # 无标签的数值单元格保持纯数值
    assert cmds[2]["props"]["text"] == "15.00万元"


def test_apply_underline_to_filled_doc_should_set_underline_on_value_run():
    """测试 _apply_underline_to_filled_doc 能给填报值拆成带下划线的 Run，且保持前缀标签无下划线"""
    import tempfile, os
    from docx import Document
    from app.agents.bid_filler_agent import _apply_underline_to_filled_doc

    doc = Document()
    doc.add_paragraph("投标人名称（单位盖章）：北京某某科技有限公司")
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name
    
    try:
        doc.save(temp_path)
        proposals = [{
            "path": "/body/p[1]",
            "original_context": "投标人名称（单位盖章）：__________________________",
            "proposed_text": "北京某某科技有限公司"
        }]
        
        _apply_underline_to_filled_doc(temp_path, proposals)
        
        res_doc = Document(temp_path)
        p = res_doc.paragraphs[0]
        assert len(p.runs) == 2
        assert p.runs[0].text == "投标人名称（单位盖章）："
        assert p.runs[0].underline is False or p.runs[0].underline is None
        assert p.runs[1].text == "北京某某科技有限公司"
        assert p.runs[1].underline is True
        assert "w:u" in p.runs[1]._element.xml
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_fill_docx_proposals_in_dom_should_preserve_real_labels_and_add_underline():
    """测试 DOM 引擎从真实 Word 节点读取原文，保留前缀标签并成功注入 OpenXML 下划线"""
    import tempfile, os
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom, _extract_prefix_from_text

    # 1. 验证 _extract_prefix_from_text 各种提炼场景
    assert _extract_prefix_from_text("投标人全称（盖章）__________________________") == "投标人全称（盖章）："
    assert _extract_prefix_from_text("地    址：__________________________") == "地    址："
    assert _extract_prefix_from_text("项目名称") == "项目名称："

    doc = Document()
    doc.add_paragraph("投标人全称（盖章）：__________________________")
    doc.add_paragraph("法定代表人（签字）：__________________________")
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name
    
    try:
        doc.save(temp_path)
        proposals = [
            {
                "path": "/body/p[1]",
                "original_context": "正文段落 1",  # 哪怕 Worker 上下文丢失，DOM 引擎仍能从真实 Word 读取
                "proposed_text": "四川某某实业有限公司"
            },
            {
                "path": "/body/p[2]",
                "original_context": "法定代表人（签字）：__________________________",
                "proposed_text": "李四"
            }
        ]
        
        count = fill_docx_proposals_in_dom(temp_path, proposals)
        assert count == 2
        
        res_doc = Document(temp_path)
        p1 = res_doc.paragraphs[0]
        assert len(p1.runs) == 2
        assert p1.runs[0].text == "投标人全称（盖章）："
        assert p1.runs[0].underline is False or p1.runs[0].underline is None
        assert p1.runs[1].text == "四川某某实业有限公司"
        assert p1.runs[1].underline is True
        assert "w:u" in p1.runs[1]._element.xml

        p2 = res_doc.paragraphs[1]
        assert len(p2.runs) == 2
        assert p2.runs[0].text == "法定代表人（签字）："
        assert p2.runs[1].text == "李四"
        assert "w:u" in p2.runs[1]._element.xml
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_fill_docx_proposals_underline_policy_outside_vs_inside_table():
    """测试 DOM 引擎策略：表格外正文填报施加下划线，表格内单元格填报取消下划线"""
    import tempfile, os
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom

    doc = Document()
    doc.add_paragraph("投标人名称（单位盖章）：__________________________")
    tbl = doc.add_table(rows=1, cols=2)
    tbl.rows[0].cells[0].paragraphs[0].text = "投标总价："
    tbl.rows[0].cells[1].paragraphs[0].text = "__________________________"

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name

    try:
        doc.save(temp_path)
        proposals = [
            {
                "path": "/body/p[1]",
                "original_context": "投标人名称（单位盖章）：__________________________",
                "proposed_text": "北京某某科技有限公司"
            },
            {
                "path": "/body/tbl[1]/tr[1]/tc[2]",
                "original_context": "表格第 1 个表，第 1 行，第 2 列",
                "proposed_text": "15.00万元"
            }
        ]

        count = fill_docx_proposals_in_dom(temp_path, proposals)
        assert count == 2

        res_doc = Document(temp_path)
        # 1. 验证表格外正文段落：数据值带有下划线
        p_body = res_doc.paragraphs[0]
        assert len(p_body.runs) == 2
        assert p_body.runs[1].text == "北京某某科技有限公司"
        assert p_body.runs[1].underline is True
        assert "w:u" in p_body.runs[1]._element.xml

        # 2. 验证表格内单元格：数据值没有下划线
        p_cell = res_doc.tables[0].rows[0].cells[1].paragraphs[0]
        assert p_cell.runs[0].text == "15.00万元"
        assert p_cell.runs[0].underline is False or p_cell.runs[0].underline is None
        assert "w:u" not in p_cell.runs[0]._element.xml
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_fill_docx_proposals_inplace_sub_replacement_preserves_surrounding_text():
    """测试核心算法：原位切片替换 100% 物理保留占位符前后的所有模板文本，彻底防止丢失原文"""
    import tempfile, os
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom

    doc = Document()
    doc.add_paragraph("根据贵方的 SZDZ-2026-NG008 号招标文件，正式授权下述签字人____代表我方____公司（投标人的名称），全权处理本次项目投标。")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name

    try:
        doc.save(temp_path)
        proposals = [
            {
                "path": "/body/p[1]",
                "original_context": "根据贵方的 SZDZ-2026-NG008 号招标文件，正式授权下述签字人____代表我方....",
                "proposed_text": "张三"
            }
        ]

        count = fill_docx_proposals_in_dom(temp_path, proposals)
        assert count == 1

        res_doc = Document(temp_path)
        p = res_doc.paragraphs[0]
        # 断言应该切片为 3 段 Run：[前文模板, 填入值, 后文模板]
        assert len(p.runs) == 3
        assert p.runs[0].text == "根据贵方的 SZDZ-2026-NG008 号招标文件，正式授权下述签字人"
        assert p.runs[0].underline is False or p.runs[0].underline is None
        assert p.runs[1].text == "张三"
        assert p.runs[1].underline is True
        assert p.runs[2].text == "代表我方____公司（投标人的名称），全权处理本次项目投标。"
        assert p.runs[2].underline is False or p.runs[2].underline is None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)



def test_db_tools_quotation_and_market_price_should_return_full_bom():
    """测试财务报价及指导单价检索 DB 工具能正确支持全量 BOM 成本测算合价与模糊词条组合联查"""
    from app.agents.tools.bid_db_tools import query_market_price_reference_tool, query_financial_quotation_tool

    # 1. 验证 query_market_price_reference_tool 能自动切词并联查 CostEstimate 的单价和合价
    res_inverter = query_market_price_reference_tool.invoke({"item_name": "组串式逆变器 华为 110kW"})
    assert "单价" in res_inverter and "11555.0" in res_inverter

    # 2. 验证并网柜指导单价与实际BOM合价的透查
    res_cabinet = query_market_price_reference_tool.invoke({"item_name": "并网柜"})
    assert "9180.35" in res_cabinet and "18360.7" in res_cabinet

    # 3. 验证财务接口通过 cost_estimates 关键字段一次性直接拉取完整的分项清单表
    res_bom = query_financial_quotation_tool.invoke({"document_id": "06a4abb2-4817-43fc-aa6f-f5f4901025ae", "field_key": "cost_estimates"})
    assert "673492.47" in res_bom and "69330.0" in res_bom and "18360.7" in res_bom


def test_parse_proposals_unescaped_quotes_and_object_recovery():
    """测试 Worker 提案解析器能否容错自动修复内层未转义双引号，并在语法崩溃时实施逐个对象拯救机制"""
    from app.agents.bid_filler_workers import _parse_proposals

    # 包含内层半角双引号 "招标编号：__号" 的日志真实范例片段
    bad_raw_json = (
        '[\n'
        '  {"path": "/body/p[1]", "original_context": "招标", "source_data": "008号", "proposed_text": "008号", '
        '"reasoning": "原文"招标编号：__号"为空白待填"},\n'
        '  {"path": "/body/tbl[1]/tr[2]/tc[1]", "proposed_text": "1", "reasoning": "正常项"}\n'
        ']'
    )

    proposals = _parse_proposals(bad_raw_json)
    assert len(proposals) == 2
    assert proposals[0]["path"] == "/body/p[1]"
    assert "招标编号" in proposals[0]["reasoning"]
    assert proposals[1]["proposed_text"] == "1"

