"""
OfficeCLIMCPClient - 基于 Model Context Protocol 规范的 Office CLI 客户端适配器

本模块提供连接并调用 OfficeCLI MCP Server 工具的适配器，
可将 MCP Server 中暴露的底层文档处理 Tool 适配为 LangChain / LangGraph Agent
可以直接调用的标准 `@tool` 工具列表。

遵循项目规范：
1. 全面使用中文注释与 Docstring；
2. 全面使用 Type Hints 类型提示；
3. 使用 loguru 进行详细日志记录；
4. 防御性编程与尽早返回（Early Return）。
"""

import json
from typing import Dict, Any, List, Optional
from loguru import logger
from langchain_core.tools import tool

from app.mcp.office_cli_server import (
    officecli_check_available,
    officecli_create_docx,
    officecli_query_docx,
    officecli_batch_update_docx,
    officecli_add_table_row,
    officecli_merge_template,
)


class OfficeCLIMCPClient:
    """
    Office CLI MCP Client 管理类，负责 MCP 协议层工具调度的路由与包装
    """

    def __init__(self):
        logger.info("初始化 OfficeCLIMCPClient 客户端适配器实例")

    async def check_available(self) -> Dict[str, Any]:
        """查询 MCP Server 的 OfficeCLI 引擎可用状态"""
        return await officecli_check_available()

    async def create_docx(self, file_path: str) -> Dict[str, Any]:
        """通过 MCP 服务创建空白 Word 文档"""
        return await officecli_create_docx(file_path=file_path)

    async def query_structure(self, file_path: str, selector: str = "paragraph") -> Dict[str, Any]:
        """通过 MCP 服务查询 Word DOM 节点结构"""
        return await officecli_query_docx(file_path=file_path, selector=selector)

    async def batch_update(self, file_path: str, commands_json_str: str) -> Dict[str, Any]:
        """通过 MCP 服务提交 Word 批处理事务"""
        return await officecli_batch_update_docx(file_path=file_path, commands_json_str=commands_json_str)

    async def add_table_row(self, file_path: str, table_path: str, row_values_json_str: str) -> Dict[str, Any]:
        """通过 MCP 服务为 Word 表格追加新行"""
        return await officecli_add_table_row(file_path=file_path, table_path=table_path, row_values_json_str=row_values_json_str)

    async def merge_template(self, template_path: str, output_path: str, data_json_str: str) -> Dict[str, Any]:
        """通过 MCP 服务进行模版变量数据合并"""
        return await officecli_merge_template(template_path=template_path, output_path=output_path, data_json_str=data_json_str)


# 全局客户端单例
office_cli_mcp_client = OfficeCLIMCPClient()


# ============================================================
# LangChain / LangGraph Agent 适配的 MCP 工具列表 (@tool)
# ============================================================

@tool
async def mcp_officecli_query_docx(file_path: str, selector: str = "paragraph") -> str:
    """[MCP Protocol Tool] 查询指定 Word 文档 (.docx) 中 DOM 节点的结构与选择器 Path (如 /body/p[1] 或 /body/tbl[1])。"""
    try:
        res = await office_cli_mcp_client.query_structure(file_path, selector)
        if res.get("success"):
            return res.get("structure", "")
        return f"MCP 查询失败: {res.get('error')}"
    except Exception as e:
        logger.exception(f"调用 MCP 结合工具 mcp_officecli_query_docx 产生异常: {e}")
        return f"MCP 工具异常: {str(e)}"


@tool
async def mcp_officecli_batch_update_docx(file_path: str, commands_json_str: str) -> str:
    """[MCP Protocol Tool] 使用 OfficeCLI 引擎对 Word 文档提交 JSON 批处理修改事务。commands_json_str 为 JSON 数组字符串，例如 [{"command":"set","path":"/body/p[1]","props":{"text":"新文本"}}]。"""
    try:
        res = await office_cli_mcp_client.batch_update(file_path, commands_json_str)
        if res.get("success"):
            return f"成功执行 {res.get('executed_commands_count')} 条指令"
        return f"MCP 批处理更新失败: {res.get('error')}"
    except Exception as e:
        logger.exception(f"调用 MCP 结合工具 mcp_officecli_batch_update_docx 产生异常: {e}")
        return f"MCP 工具异常: {str(e)}"


@tool
async def mcp_officecli_add_table_row(file_path: str, table_path: str, row_values_json_str: str) -> str:
    """[MCP Protocol Tool] 使用 OfficeCLI 为指定表格动态追加一行新记录并填充单元格数据。row_values_json_str 为 JSON 数组字符串，例如 ["1", "高级工程师", "10年"]。"""
    try:
        res = await office_cli_mcp_client.add_table_row(file_path, table_path, row_values_json_str)
        if res.get("success"):
            return f"成功追加表格行数据到 {table_path}"
        return f"MCP 动态追加表格行失败: {res.get('error')}"
    except Exception as e:
        logger.exception(f"调用 MCP 结合工具 mcp_officecli_add_table_row 产生异常: {e}")
        return f"MCP 工具异常: {str(e)}"


def get_office_cli_mcp_tools() -> List[Any]:
    """
    获取由 MCP 协议暴露并包装供 Agent 调用的完整 Tool 列表
    """
    return [
        mcp_officecli_query_docx,
        mcp_officecli_batch_update_docx,
        mcp_officecli_add_table_row,
    ]
