"""
OfficeCLI MCP Protocol Server & Client 单元测试

遵循 AGENTS.md 测试规范：
1. 位置对齐在 tests/unit/ 目录下；
2. 函数命名遵循 test_<功能>_<场景>_<期望结果> 格式；
3. 包含正常情况、异常情况与边界情况测试；
4. 标记 @pytest.mark.asyncio。
"""

import os
import tempfile
import json
import pytest

from app.mcp.office_cli_server import (
    officecli_check_available,
    officecli_create_docx,
    officecli_query_docx,
    officecli_batch_update_docx,
    officecli_add_table_row,
    officecli_merge_template,
)
from app.mcp.office_cli_client import (
    office_cli_mcp_client,
    get_office_cli_mcp_tools,
    mcp_officecli_query_docx,
    mcp_officecli_batch_update_docx,
)


@pytest.mark.asyncio
async def test_mcp_server_check_available_should_return_success_dict():
    """测试 MCP Server 检查 OfficeCLI 可用性工具"""
    res = await officecli_check_available()
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert "available" in res


@pytest.mark.asyncio
async def test_mcp_server_create_and_query_docx_should_succeed():
    """测试 MCP Server 创建空白文档与结构查询工具"""
    from app.services.office_cli_service import office_cli_service
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "mcp_test.docx")
        
        # 1. 创建文档
        create_res = await officecli_create_docx(file_path=test_file)
        assert create_res.get("success") is True
        assert os.path.exists(test_file)

        # 2. 查询 DOM 结构
        query_res = await officecli_query_docx(file_path=test_file, selector="paragraph")
        assert query_res.get("success") is True
        assert "structure" in query_res

        # 3. 释放句柄
        await office_cli_service.save_and_close(test_file)


@pytest.mark.asyncio
async def test_mcp_server_batch_update_should_apply_commands():
    """测试 MCP Server 提交批处理指令字典数组修改 Word"""
    from app.services.office_cli_service import office_cli_service
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "mcp_batch_test.docx")
        await officecli_create_docx(file_path=test_file)

        cmds = [
            {
                "command": "add",
                "parent": "/",
                "type": "paragraph",
                "props": {"text": "MCP 测试项目名称：招投标自动化项目"}
            }
        ]
        cmds_str = json.dumps(cmds, ensure_ascii=False)

        batch_res = await officecli_batch_update_docx(file_path=test_file, commands_json_str=cmds_str)
        assert batch_res.get("success") is True
        assert batch_res.get("executed_commands_count") == 1

        await office_cli_service.save_and_close(test_file)


@pytest.mark.asyncio
async def test_mcp_server_query_nonexistent_file_should_return_error():
    """边界异常测试：对不存在的文件进行 MCP 查询应优雅返回错误信息"""
    res = await officecli_query_docx(file_path="non_existent_file_path_xyz.docx")
    assert res.get("success") is False
    assert "目标文档不存在" in res.get("error", "")


@pytest.mark.asyncio
async def test_mcp_client_tools_integration_should_succeed():
    """测试 MCP 客户端适配器及 LangChain Agent 工具获取"""
    from app.services.office_cli_service import office_cli_service
    tools = get_office_cli_mcp_tools()
    assert len(tools) == 3
    tool_names = [t.name for t in tools]
    assert "mcp_officecli_query_docx" in tool_names
    assert "mcp_officecli_batch_update_docx" in tool_names
    assert "mcp_officecli_add_table_row" in tool_names

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "mcp_agent_tool_test.docx")
        await office_cli_mcp_client.create_docx(test_file)

        # 通过 Agent 工具 ainvoke 调用
        query_out = await mcp_officecli_query_docx.ainvoke({"file_path": test_file, "selector": "paragraph"})
        assert query_out is not None
        assert "MCP 查询失败" not in query_out

        await office_cli_service.save_and_close(test_file)
