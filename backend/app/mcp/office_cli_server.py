"""
OfficeCLI MCP Server - 基于 Model Context Protocol 规范的 Office CLI 工具服务端

本模块将底层 OfficeCLIService 包装为标准的 MCP (Model Context Protocol) Server，
为 LangGraph/LangChain 架构的招投标 Agent 提供可动态感知与调用的无头 Word 文档自动化工具集。

遵循项目规范：
1. 全面使用中文注释与 Docstring；
2. 全面使用 Type Hints 类型提示；
3. 使用 loguru 进行详细日志记录；
4. 防御性编程与尽早返回（Early Return）。
"""

import json
import os
from typing import Dict, Any, List, Optional
from loguru import logger
from mcp.server.fastmcp import FastMCP

from app.services.office_cli_service import office_cli_service

# 初始化 FastMCP 服务实例
mcp_server = FastMCP(
    name="OfficeCLI-MCP-Server",
    instructions="提供基于 OfficeCLI 的 Word 文档 (.docx) 结构查询、批量修改、表格追加与模板合并的 MCP 标准工具集。"
)


@mcp_server.tool(
    name="officecli_check_available",
    description="检查系统中的 OfficeCLI 引擎是否处于可用状态，并返回版本信息。"
)
async def officecli_check_available() -> Dict[str, Any]:
    """
    检查 OfficeCLI 引擎可用性
    """
    logger.info("MCP Tool [officecli_check_available] 被调用")
    try:
        is_available = await office_cli_service.check_available()
        return {
            "success": True,
            "available": is_available,
            "cli_path": office_cli_service.cli_path,
            "message": "OfficeCLI 引擎在线正常" if is_available else "OfficeCLI 引擎不可用"
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_check_available 执行异常: {str(e)}")
        return {
            "success": False,
            "available": False,
            "error": str(e)
        }


@mcp_server.tool(
    name="officecli_create_docx",
    description="根据指定文件路径创建一个全新的空白 Word (.docx) 文档。"
)
async def officecli_create_docx(file_path: str) -> Dict[str, Any]:
    """
    创建空白 Word 文档
    :param file_path: 目标文件落盘路径 (.docx)
    """
    logger.info(f"MCP Tool [officecli_create_docx] 被调用, file_path: {file_path}")
    if not file_path:
        return {"success": False, "error": "文件路径 file_path 不能为空"}

    try:
        output = await office_cli_service.create_blank_docx(file_path)
        return {
            "success": True,
            "file_path": file_path,
            "raw_output": output,
            "message": f"成功创建空白 Word 文档: {file_path}"
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_create_docx 执行异常: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp_server.tool(
    name="officecli_query_docx",
    description="查询指定 Word 文档 (.docx) 中 DOM 节点的结构与选择器 Path (如 'paragraph' / 'table')。"
)
async def officecli_query_docx(file_path: str, selector: str = "paragraph") -> Dict[str, Any]:
    """
    查询 Word 文档结构
    :param file_path: Word 文档绝对/相对路径
    :param selector: 元素选择器 ('paragraph', 'table', 'cell')
    """
    logger.info(f"MCP Tool [officecli_query_docx] 被调用, file_path: {file_path}, selector: {selector}")
    if not os.path.exists(file_path):
        return {"success": False, "error": f"目标文档不存在: {file_path}"}

    try:
        structure_str = await office_cli_service.query_structure(file_path, selector)
        return {
            "success": True,
            "file_path": file_path,
            "selector": selector,
            "structure": structure_str
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_query_docx 执行异常: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp_server.tool(
    name="officecli_batch_update_docx",
    description="使用 JSON 指令数组对 Word 文档提交原子化批处理修改事务 (支持原位替换段落文本、格式继承、表格设置等)。"
)
async def officecli_batch_update_docx(file_path: str, commands_json_str: str) -> Dict[str, Any]:
    """
    提交 Word 节点批处理更新
    :param file_path: 待修改 Word 文档路径
    :param commands_json_str: JSON 数组字符串，例如 '[{"command":"set","path":"/body/p[1]","props":{"text":"新内容"}}]'
    """
    logger.info(f"MCP Tool [officecli_batch_update_docx] 被调用, file_path: {file_path}")
    if not os.path.exists(file_path):
        return {"success": False, "error": f"目标文档不存在: {file_path}"}

    try:
        commands = json.loads(commands_json_str) if isinstance(commands_json_str, str) else commands_json_str
        if not isinstance(commands, list):
            return {"success": False, "error": "commands 必须为 JSON 列表数组"}

        output = await office_cli_service.apply_batch(file_path, commands)
        await office_cli_service.save_and_close(file_path)

        return {
            "success": True,
            "file_path": file_path,
            "executed_commands_count": len(commands),
            "raw_output": output,
            "message": f"成功批处理更新 {len(commands)} 条指令"
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_batch_update_docx 执行异常: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp_server.tool(
    name="officecli_add_table_row",
    description="为指定 Word 表格节点动态追加一行新数据并按列填充内容。"
)
async def officecli_add_table_row(file_path: str, table_path: str, row_values_json_str: str) -> Dict[str, Any]:
    """
    动态向表格追加行
    :param file_path: 目标 Word 文件路径
    :param table_path: 表格 Path，例如 '/body/tbl[1]'
    :param row_values_json_str: JSON 数组字符串，包含行内各单元格文本，如 '["1", "项目经理", "高级工程师"]'
    """
    logger.info(f"MCP Tool [officecli_add_table_row] 被调用, file_path: {file_path}, table_path: {table_path}")
    if not os.path.exists(file_path):
        return {"success": False, "error": f"目标文档不存在: {file_path}"}

    try:
        row_values = json.loads(row_values_json_str) if isinstance(row_values_json_str, str) else row_values_json_str
        if not isinstance(row_values, list):
            return {"success": False, "error": "row_values 必须为 JSON 列表数组"}

        cmds = [{"command": "add", "parent": table_path, "type": "row"}]
        for col_idx, val in enumerate(row_values):
            cmds.append({
                "command": "set",
                "path": f"{table_path}/row[last()]/cell[{col_idx + 1}]",
                "props": {"text": str(val)}
            })

        output = await office_cli_service.apply_batch(file_path, cmds)
        await office_cli_service.save_and_close(file_path)

        return {
            "success": True,
            "file_path": file_path,
            "table_path": table_path,
            "added_row_values": row_values,
            "raw_output": output
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_add_table_row 执行异常: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp_server.tool(
    name="officecli_merge_template",
    description="使用键值字典自动填充 Word 模版文件中的 {{占位符}} 变量，并导出新文件。"
)
async def officecli_merge_template(template_path: str, output_path: str, data_json_str: str) -> Dict[str, Any]:
    """
    模板占位符变量数据合并
    :param template_path: 模版文档路径
    :param output_path: 导出新文档路径
    :param data_json_str: 键值字典 JSON 字符串，例如 '{"project_name": "某标段项目"}'
    """
    logger.info(f"MCP Tool [officecli_merge_template] 被调用, template_path: {template_path}, output_path: {output_path}")
    if not os.path.exists(template_path):
        return {"success": False, "error": f"模版文档不存在: {template_path}"}

    try:
        data = json.loads(data_json_str) if isinstance(data_json_str, str) else data_json_str
        if not isinstance(data, dict):
            return {"success": False, "error": "data 必须为 JSON 键值字典"}

        output = await office_cli_service.merge_template(template_path, output_path, data)
        return {
            "success": True,
            "template_path": template_path,
            "output_path": output_path,
            "merged_keys_count": len(data),
            "raw_output": output
        }
    except Exception as e:
        logger.exception(f"MCP Tool officecli_merge_template 执行异常: {str(e)}")
        return {"success": False, "error": str(e)}


def run_mcp_server():
    """
    运行 Stdio 模式的 OfficeCLI MCP Server 主入口
    """
    logger.info("正在启动 OfficeCLI MCP Server (stdio 模式)...")
    mcp_server.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
