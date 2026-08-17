"""
BidFiller Worker & Office CLI MCP 工具直写与闭环修复单元测试 (test_bid_filler_worker.py)

遵循 AGENTS.md 测试规范：
1. 位于 tests/unit/ 目录下；
2. 函数命名遵循 test_<功能>_<场景>_<期望结果> 格式；
3. 包含正常情况、异常情况与边界情况测试；
4. 标记 @pytest.mark.asyncio。
"""

import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock

from app.agents.tools.office_cli_agent_tools import (
    officecli_batch_fill_sentence_tool,
    officecli_fill_table_rows_tool,
    get_all_office_cli_agent_tools,
)
from app.agents.bid_filler_agent import (
    supervisor_audit_node,
    should_repair,
    BidFillerState,
)
from app.mcp.office_cli_server import officecli_create_docx
from app.services.office_cli_service import office_cli_service


@pytest.mark.asyncio
async def test_officecli_batch_fill_sentence_tool_should_succeed():
    """测试长句多槽位原子批处理写盘工具"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "batch_fill_test.docx")
        await officecli_create_docx(file_path=test_file)

        # 1. 预先加入 2 个段落供替换写盘
        add_cmds = [
            {"command": "add", "parent": "/", "type": "paragraph", "props": {"text": "投标人名称：______"}},
            {"command": "add", "parent": "/", "type": "paragraph", "props": {"text": "法定代表人：______"}},
        ]
        await office_cli_service.apply_batch(test_file, add_cmds)

        # 2. 批量原子更新
        updates = [
            {"path": "/body/p[1]", "value": "投标人名称：聚猫科技股份有限公司"},
            {"path": "/body/p[2]", "value": "法定代表人：张三"},
        ]
        updates_json = json.dumps(updates, ensure_ascii=False)

        res = await officecli_batch_fill_sentence_tool.ainvoke({
            "file_path": test_file,
            "updates_json_str": updates_json
        })
        assert "成功" in res

        await office_cli_service.save_and_close(test_file)


@pytest.mark.asyncio
async def test_officecli_fill_table_rows_tool_auto_index_should_succeed():
    """测试表格全量追加填充工具（自动生成 1..N 递增序号与表头保护）"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "table_fill_test.docx")
        await officecli_create_docx(file_path=test_file)

        # 1. 预先加入 1 个表格
        add_tbl_cmds = [
            {"command": "add", "parent": "/", "type": "table"}
        ]
        await office_cli_service.apply_batch(test_file, add_tbl_cmds)

        # 2. 模拟插入 2 行数据，auto_index=True 自动在第1列注入序号 1, 2
        rows = [
            ["项目经理", "张三", "PMP"],
            ["技术负责人", "李四", "高级工程师"]
        ]
        rows_json = json.dumps(rows, ensure_ascii=False)

        res = await officecli_fill_table_rows_tool.ainvoke({
            "file_path": test_file,
            "table_path": "/body/tbl[1]",
            "rows_json_str": rows_json,
            "auto_index": True
        })
        assert "成功" in res

        await office_cli_service.save_and_close(test_file)


def test_get_all_office_cli_agent_tools_count_should_be_six():
    """测试 Office CLI Agent 工具导出列表数量 (共 6 个工具)"""
    tools = get_all_office_cli_agent_tools()
    assert len(tools) == 6


def test_supervisor_audit_node_should_pass_when_no_unfilled_slots():
    """测试 Supervisor 质量审查：无未填槽位时直接通过"""
    state: BidFillerState = {
        "document_id": "doc123",
        "original_context": "",
        "slot_analysis": None,
        "worker_proposals": None,
        "db_session": None,
        "company_profile": MagicMock(),
        "original_docx": None,
        "docx_temp_path": "/invalid/non_existent.docx",
        "custom_instructions": None,
        "category_hints": None,
        "repair_count": 0,
        "max_repair_rounds": 2,
        "repair_instructions_map": None,
        "audit_passed": None,
        "audit_items": [],
        "review_findings": [],
        "audit_report": None,
        "filled_docx_bytes": None,
    }

    result = supervisor_audit_node(state)
    assert result.get("audit_passed") is True


def test_should_repair_routing_logic():
    """测试 Supervisor 审核条件边路由跳转"""
    state_pass: BidFillerState = {"audit_passed": True}  # type: ignore
    assert should_repair(state_pass) == "write_docx_node"

    state_fail: BidFillerState = {"audit_passed": False}  # type: ignore
    assert should_repair(state_fail) == "agent_fill_node"


def test_parse_proposals_should_skip_info_tables_and_extract_valid_table_rows():
    """测试 _parse_proposals 智能跳过前置数据来源说明表，准确提炼 /body/tbl[2] 等写盘明细表格"""
    from app.agents.bid_filler_workers import _parse_proposals

    raw_markdown = """
### 【投标配置及分项报价表（投标报价分析表）】— 数据来源与核验

| 数据项 | 检索结果 | 说明 |
|---|---|---|
| 项目名称 | 和烁热能公司屋顶（400kW）分布式光伏发电项目 | 项目元数据库直查 |
| 招标编号 | SZDZ-2026-NG008号 | 项目元数据库直查 |
| 投标总报价（小写） | 1017934.21元 | 财务库直查 |

### ✅ 写盘明细表

| 序号 | DOM 节点路径 | 替换前模板原文 | 实际填入/扩写结果 | 提议类型 | 写盘状态 |
|---|---|---|---|---|---|
| 1 | /body/p[@paraId=31FC6AF8] | 招标编号：号 项目名称： | 招标编号：SZDZ-2026-NG008号 项目名称：某某项目 | sentence_batch | ✅ 已提交刷盘 |
| 2 | /body/tbl[2]（16 行数据明细） | 18 行空白数据行 | [["光伏组件", "630Wp", "国内一线", "块", "763", "882.69", "673492.47", "合规"]] | table_rows | ✅ 已提交刷盘 |
"""
    proposals = _parse_proposals(raw_markdown)
    assert len(proposals) == 2
    assert proposals[0]["path"] == "/body/p[@paraId=31FC6AF8]"
    assert proposals[0]["type"] == "sentence_batch"
    assert proposals[1]["path"] == "/body/tbl[2]"
    assert proposals[1]["type"] == "table_rows"
    assert "光伏组件" in proposals[1]["proposed_text"]


def test_fill_docx_proposals_in_dom_table_overwrite_and_auto_index():
    """测试 DOM 引擎表格填报：原位覆盖已有空白行、序号列智能对齐与末尾汇总行（投标总报价/交货期限）保护"""
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom

    doc = Document()
    tbl = doc.add_table(rows=6, cols=9)
    # Row 0: 表头
    headers = ["序号", "标的物名称", "品牌、规格、型号", "生产厂家", "单位", "数量", "单价", "合价", "备注"]
    for c_idx, h in enumerate(headers):
        tbl.rows[0].cells[c_idx].text = h

    # Rows 1-3: 空白数据行
    for r_idx in range(1, 4):
        for c_idx in range(9):
            tbl.rows[r_idx].cells[c_idx].text = ""

    # Rows 4-5: 底部汇总与落款行
    tbl.rows[4].cells[0].text = "投标总报价：大写：壹佰万元整"
    tbl.rows[5].cells[0].text = "交货期限：60天内完成"

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name

    try:
        doc.save(temp_path)

        # 传入未提供序号的 8 列业务数据
        matrix = [
            ["光伏组件", "630Wp", "国产", "块", "763", "882.69", "673492.47", "符合要求"],
            ["逆变器", "110kW", "国产", "台", "6", "11555", "69330", "符合要求"],
        ]
        proposals = [
            {
                "path": "/body/tbl[1]",
                "original_context": "空白表格",
                "proposed_text": json.dumps(matrix, ensure_ascii=False),
                "type": "table_rows"
            }
        ]

        count = fill_docx_proposals_in_dom(temp_path, proposals)
        assert count >= 2

        res_doc = Document(temp_path)
        res_tbl = res_doc.tables[0]

        # 验证 Row 1: 第一列自动注入序号 1，且后续字段完全对齐
        r1_cells = [c.text.strip() for c in res_tbl.rows[1].cells]
        assert r1_cells[0] == "1"
        assert r1_cells[1] == "光伏组件"
        assert r1_cells[2] == "630Wp"
        assert r1_cells[3] == "国产"
        assert r1_cells[4] == "块"
        assert r1_cells[5] == "763"
        assert r1_cells[6] == "882.69"
        assert r1_cells[7] == "673492.47"
        assert r1_cells[8] == "符合要求"

        # 验证 Row 2: 第一列自动注入序号 2
        r2_cells = [c.text.strip() for c in res_tbl.rows[2].cells]
        assert r2_cells[0] == "2"
        assert r2_cells[1] == "逆变器"

        # 验证底部汇总行完好无损未被覆盖
        assert "投标总报价" in res_tbl.rows[4].cells[0].text
        assert "交货期限" in res_tbl.rows[5].cells[0].text

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_parse_proposals_should_auto_expand_markdown_range_paths():
    """测试 Markdown 表格解析器：自动将连续的范围概括路径 (如 /body/tbl[6]/tr[2]~tr[19]) 展开为递增行号独立提案"""
    from app.agents.bid_filler_workers import _parse_proposals

    raw_markdown = """
### 写盘明细表
| 序号 | DOM 节点路径 | 替换前模板原文 | 实际填入/扩写结果 | 提议类型 | 写盘状态 |
|---|---|---|---|---|---|
| 1 | /body/tbl[6] | 表头... | 表头原样保留 | — | 已保护 |
| 2 | /body/tbl[6]/tr[2]~tr[19] | 空白 | 标的物A技术响应承诺详情 | sentence_batch | 已入刷盘队列 |
| 3 | /body/tbl[6]/tr[2]~tr[19] | 同上 | 标的物B技术响应承诺详情 | sentence_batch | 已入刷盘队列 |
| 4 | /body/tbl[6]/tr[2]~tr[19] | 同上 | 标的物C技术响应承诺详情 | sentence_batch | 已入刷盘队列 |
| 5 | /body/tbl[6]/tr[2]~tr[19] | 同上 | 标的物D技术响应承诺详情 | sentence_batch | 已入刷盘队列 |
"""

    proposals = _parse_proposals(raw_markdown)
    assert len(proposals) == 4
    # 验证 4 条概括路径已被成功自动展开为 tr[2] 到 tr[5] 的连续物理行
    assert proposals[0]["path"] == "/body/tbl[6]/tr[2]"
    assert "标的物A" in proposals[0]["proposed_text"]
    assert proposals[1]["path"] == "/body/tbl[6]/tr[3]"
    assert "标的物B" in proposals[1]["proposed_text"]
def test_parse_proposals_should_filter_pseudo_plus_summary_syntax():
    """测试 _parse_proposals 能够纯通用地拦截过滤大模型偷懒输出的加号运算符伪拼接表达式与行级模糊路径"""
    from app.agents.bid_filler_workers import _parse_proposals

    raw_markdown = """
### 写盘明细表
| 序号 | DOM 节点路径 | 替换前模板原文 | 实际填入/扩写结果 | 提议类型 | 写盘状态 |
|---|---|---|---|---|---|
| 1 | /body/tbl[2]/tr[2] | （空单元格，序号"1"） | 条款A原文描述 + 对应技术服务承诺 + "无" + "完全响应招标文件要求，无偏离。" | text | 已提交刷盘队列 |
| 2 | /body/tbl[2]/tr[11] | "..."（扩展占位行） | 条款B要求详情 + 承诺描述 + "无" | text | 已提交刷盘队列 |
| 3 | /body/tbl[2] | 表头原样保留 | 表头原样保留 | — | 已保护 |
| 4 | /body/p[12] | 授权代表：______ | 授权代表：张三 | sentence_batch | 已入刷盘队列 |
"""
    proposals = _parse_proposals(raw_markdown)
    # 前 3 条未指定单元格的行级模糊路径与伪语法概括全部被纯通用规则拦截，仅保留真实合法的段落提案
    assert len(proposals) == 1
    assert proposals[0]["path"] == "/body/p[12]"
    assert "张三" in proposals[0]["proposed_text"]


def test_fill_docx_proposals_in_dom_formatted_json_matrix_deviation_table_should_succeed():
    """测试技术偏离表等带有换行缩进的格式化 2D 矩阵 JSON 提案能否 100% 成功刷盘到 Word 表格中"""
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom

    doc = Document()
    tbl = doc.add_table(rows=4, cols=5)
    # Row 0: 表头（序号 / 招标文件要求 / 投标文件服务承诺 / 有无偏离 / 偏离内容及原因）
    headers = ["序号", "招标文件技术要求", "投标文件对应要求的服务承诺", "有无偏离", "偏离内容及原因"]
    for c_idx, h in enumerate(headers):
        tbl.rows[0].cells[c_idx].text = h

    # 预设 3 行空白模板行
    for r_idx in range(1, 4):
        for c_idx in range(5):
            tbl.rows[r_idx].cells[c_idx].text = ""

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name

    try:
        doc.save(temp_path)

        # 模拟大模型输出的带换行符与 4 列（未带序号）的偏离表 JSON 字符串
        formatted_json_matrix = (
            "[\n"
            '  ["光伏组件：规格型号≥630Wp，数量763块...", "我方完全响应并承诺：投报天合光能...", "无", "完全响应招标文件要求，无偏离。"],\n'
            '  ["逆变器：110kW逆变器2台...", "我方完全响应并承诺：投报华为组串式逆变器...", "无", "完全响应招标文件要求，无偏离。"],\n'
            '  ["并网柜：200kW室外柜2台...", "我方完全响应并承诺：投报诺电品牌...", "无", "完全响应招标文件要求，无偏离。"],\n'
            '  ["直流电缆：PV1-F 4mm2...", "我方完全响应并承诺：投报江南品牌...", "无", "完全响应招标文件要求，无偏离。"]\n'
            "]\n"
        )

        proposals = [
            {
                "path": "/body/tbl[1]",
                "original_context": "空白偏离表格",
                "proposed_text": formatted_json_matrix,
                "value": formatted_json_matrix,
                "type": "table_rows",
                "chapter_title": "技术要求响应及偏离表"
            }
        ]

        count = fill_docx_proposals_in_dom(temp_path, proposals)
        assert count == 4

        res_doc = Document(temp_path)
        res_tbl = res_doc.tables[0]

        # 验证总行数为 5 行（1 行表头 + 4 行数据）
        assert len(res_tbl.rows) == 5

        # 验证第 1 行数据：序号自动注入为 1，4 列内容精准对齐
        r1_cells = [c.text.strip() for c in res_tbl.rows[1].cells]
        assert r1_cells[0] == "1"
        assert "光伏组件" in r1_cells[1]
        assert "天合光能" in r1_cells[2]
        assert r1_cells[3] == "无"
        assert "完全响应" in r1_cells[4]

        # 验证第 4 行数据：自动追加新行，序号为 4
        r4_cells = [c.text.strip() for c in res_tbl.rows[4].cells]
        assert r4_cells[0] == "4"
        assert "直流电缆" in r4_cells[1]
        assert "江南品牌" in r4_cells[2]

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_dual_path_merge_substantive_table_cell_proposals_should_preserve_all_cells():
    """测试实质性要求对照表等单单元格提案在双路融合时，绝不被误判为整表提案而误删其他单元格"""
    import re
    from docx import Document
    from app.agents.bid_filler_agent import fill_docx_proposals_in_dom

    # 1. 模拟 LLM 文本总结提取出的 20 个单元格提案 (tr[2]~tr[11] 的 tc[2] 与 tc[3])
    text_proposals = []
    for r in range(2, 12):
        text_proposals.append({
            "path": f"/body/tbl[1]/tr[{r}]/tc[2]/p[1]",
            "proposed_text": f"实质性要求条款内容_{r}",
            "value": f"实质性要求条款内容_{r}",
            "type": "text",
            "status": "success"
        })
        text_proposals.append({
            "path": f"/body/tbl[1]/tr[{r}]/tc[3]/p[1]",
            "proposed_text": "是",
            "value": "是",
            "type": "text",
            "status": "success"
        })

    # 2. 模拟工具调用捕获的单格权威提案（如最后一行单元格）
    chapter_collected_proposals = [
        {
            "path": "/body/tbl[1]/tr[11]/tc[3]/p[1]",
            "proposed_text": "是",
            "value": "是",
            "type": "text",
            "status": "success"
        }
    ]

    # 3. 运行双路融合逻辑
    proposals_dict = {}
    for p in text_proposals:
        p_path = str(p.get("path", "")).strip()
        if p_path:
            proposals_dict[p_path] = p

    for p in chapter_collected_proposals:
        p_path = str(p.get("path", "")).strip()
        if p_path:
            proposals_dict[p_path] = p
            if p.get("type") == "table_rows" or re.match(r'^/body/tbl\[\d+\]$', p_path):
                m_tbl = re.match(r'^(/body/tbl\[\d+\])$', p_path)
                if m_tbl:
                    tbl_prefix = m_tbl.group(1)
                    to_del = [k for k in proposals_dict.keys() if k.startswith(tbl_prefix + "/") and k != p_path]
                    for k in to_del:
                        proposals_dict.pop(k, None)

    merged_proposals = list(proposals_dict.values())
    # 验证全部 20 个单元格提案 100% 完整保留，未被误删
    assert len(merged_proposals) == 20

    # 4. 验证写盘引擎能将这 20 个单元格提案完整刷盘到 Word 文档的表格中
    doc = Document()
    tbl = doc.add_table(rows=11, cols=3)
    tbl.rows[0].cells[0].text = "序号"
    tbl.rows[0].cells[1].text = "第四章中项目需求中实质性要求"
    tbl.rows[0].cells[2].text = "是否响应"
    for r in range(1, 11):
        tbl.rows[r].cells[0].text = str(r)
        tbl.rows[r].cells[1].text = ""
        tbl.rows[r].cells[2].text = ""

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        temp_path = tf.name

    try:
        doc.save(temp_path)
        count = fill_docx_proposals_in_dom(temp_path, merged_proposals)
        assert count == 20

        res_doc = Document(temp_path)
        res_tbl = res_doc.tables[0]
        # 验证 10 行数据均已成功填入实质性要求与“是”
        for r in range(1, 11):
            assert f"实质性要求条款内容_{r+1}" in res_tbl.rows[r].cells[1].text
            assert res_tbl.rows[r].cells[2].text.strip() == "是"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)



