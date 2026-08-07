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


def test_get_all_office_cli_agent_tools_count_should_be_five():
    """测试 Office CLI Agent 工具导出列表数量"""
    tools = get_all_office_cli_agent_tools()
    assert len(tools) == 5


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
