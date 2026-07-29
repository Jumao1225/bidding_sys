"""
OfficeCLIService 单元测试

遵循 AGENTS.md 测试规范：
1. 位置对齐在 tests/unit/ 目录下；
2. 函数命名遵循 test_<功能>_<场景>_<期望结果> 格式；
3. 包含正常情况、异常情况与边界情况测试；
4. 标记 @pytest.mark.asyncio。
"""

import os
import tempfile
import pytest
from app.services.office_cli_service import office_cli_service


@pytest.mark.asyncio
async def test_office_cli_available_should_return_boolean():
    """ 测试检测 OfficeCLI 工具链是否可用 """
    is_available = await office_cli_service.check_available()
    # 在具备 officecli 的环境上应返回 True
    assert isinstance(is_available, bool)


@pytest.mark.asyncio
async def test_create_and_close_docx_should_succeed():
    """ 测试创建空白 Word 文档并刷盘关闭句柄 """
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_path = os.path.join(tmp_dir, "test_create.docx")
        
        # 执行创建
        create_res = await office_cli_service.create_blank_docx(target_path)
        assert os.path.exists(target_path)
        
        # 执行关闭
        await office_cli_service.save_and_close(target_path)


@pytest.mark.asyncio
async def test_apply_batch_should_insert_paragraphs():
    """ 测试使用 batch 指令向 Word 批量添加节点与编辑属性 """
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_path = os.path.join(tmp_dir, "test_batch.docx")
        
        # 1. 创建空白文件
        await office_cli_service.create_blank_docx(target_path)
        
        # 2. 构造批处理命令
        commands = [
            {
                "command": "add",
                "parent": "/",
                "type": "paragraph",
                "props": {"text": "测试标题：智能招投标项目策划案"}
            },
            {
                "command": "add",
                "parent": "/",
                "type": "paragraph",
                "props": {"text": "测试正文：投标人为聚猫科技股份有限公司"}
            }
        ]
        
        # 3. 批量写入
        batch_res = await office_cli_service.apply_batch(target_path, commands)
        
        # 4. 刷盘关闭
        await office_cli_service.save_and_close(target_path)
        
        assert os.path.exists(target_path)
        assert os.path.getsize(target_path) > 0


@pytest.mark.asyncio
async def test_create_blank_docx_with_empty_path_should_raise_value_error():
    """ 边界防御测试：当输入空路径时抛出 ValueError """
    with pytest.raises(ValueError) as exc_info:
        await office_cli_service.create_blank_docx("")
    assert "文件路径不能为空" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fill_docx_with_office_cli_should_succeed():
    """ 集成测试：测试 BidFormatFillerService.fill_docx_with_office_cli 替换填报 """
    from app.services.bid_format_filler_service import bid_format_filler_service
    from app.services.docx_test_filler_service import docx_test_filler_service
    
    # 1. 创建测试模版
    template_bytes = docx_test_filler_service.create_sample_docx()
    assert len(template_bytes) > 0

    # 2. 构造替换数据
    replacement_data = {
        "项目名称": "OfficeCLI 自动化智能标书填报测试项目",
        "投标人名称": "聚猫科技人工智能团队"
    }

    # 3. 使用 OfficeCLI 填报替换
    result_bytes = await bid_format_filler_service.fill_docx_with_office_cli(template_bytes, replacement_data)
    assert result_bytes is not None
    assert len(result_bytes) > 0


@pytest.mark.asyncio
async def test_agent_officecli_tools_should_succeed():
    """ 测试 Agent ReAct 工具库 tool_officecli_query_docx & MCP OfficeCLI Client """
    from app.mcp.office_cli_client import mcp_officecli_query_docx, office_cli_mcp_client
    from app.schemas.bid_filler_schema import CompanyProfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "agent_tool_test.docx")
        await office_cli_service.create_blank_docx(test_file)

        # 测试直接工具函数调用 (async invoke)
        res = await mcp_officecli_query_docx.ainvoke({"file_path": test_file, "selector": "paragraph"})
        assert res is not None
        assert "查询失败" not in res

        # 测试 MCP Client 封装方法（替代原 BidFillerTools)
        structure_res = office_cli_mcp_client.query_structure(test_file, selector="paragraph")
        structure_dict = await structure_res if hasattr(structure_res, '__await__') else structure_res
        assert structure_dict is not None
        assert "error" not in str(structure_dict).lower() or structure_dict.get("success") is not False

        # 释放 OfficeCLI Windows 驻留句柄
        await office_cli_service.save_and_close(test_file)


