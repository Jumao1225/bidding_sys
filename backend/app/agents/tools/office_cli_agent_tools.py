"""
Office CLI Agent 无头工具包装模块 (office_cli_agent_tools.py)

功能：
将底层 Office CLI 引擎（结构查询、Run 级原位写盘、表格追加等）包装为 LangChain / LangGraph Agent 可调用的标准 @tool。
具备极致的日志可追踪性与排版继承保护特性。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints 类型提示；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import json
import os
from typing import Dict, Any, List, Optional
from loguru import logger
from langchain_core.tools import tool

from app.services.office_cli_service import office_cli_service


@tool
async def officecli_query_structure_tool(file_path: str, selector: str = "paragraph") -> str:
    """
    [Office CLI Tool] 查询指定 Word 文档 (.docx) 中 DOM 节点的结构与物理选择器 Path (如 '/body/p[1]' 或 '/body/tbl[1]')。

    :param file_path: Word 文档的绝对/相对文件路径
    :param selector: 元素选择器类型 ('paragraph', 'table', 'cell')
    :return: 包含物理 Path 与内部文本的 XML/DOM 结构文本
    """
    logger.info(f"📄 [OfficeCLI Tool] officecli_query_structure_tool 被调用, file: '{file_path}', selector: '{selector}'")
    if not file_path or not os.path.exists(file_path):
        logger.error(f"📄 [OfficeCLI Tool] 无法查询，目标 Word 文件不存在: {file_path}")
        return f"[错误: 目标文件不存在 {file_path}]"

    try:
        structure_str = await office_cli_service.query_structure(file_path, selector)
        logger.info(f"📄 [OfficeCLI Tool] 成功查询到结构，字符长度: {len(structure_str)}")
        return structure_str
    except Exception as e:
        logger.exception(f"📄 [OfficeCLI Tool] 查询结构异常: {str(e)}")
        return f"[查询文档结构异常: {str(e)}]"


@tool
async def officecli_write_slot_value_tool(file_path: str, path: str, value: str) -> str:
    """
    [Office CLI Tool] 使用 Office CLI 引擎对 Word 文档指定节点 Path (如 '/body/p[12]') 进行 100% 格式继承的原位值替换。
    不会破坏前导 Label 文本的加粗、字体、字号属性。

    :param file_path: 待修改 Word 文档路径
    :param path: 目标节点的物理 Path (如 '/body/p[12]')
    :param value: 欲填入的真实数据文本 (如 '聚猫科技股份有限公司')
    :return: 执行结果描述
    """
    logger.info(f"✍️ [OfficeCLI Tool] officecli_write_slot_value_tool 被调用, file: '{file_path}', path: '{path}', 填入值: '{value}'")
    if not file_path or not os.path.exists(file_path):
        return f"[错误: 目标文件不存在 {file_path}]"
    if not path or value is None:
        return "[错误: 节点 path 或替换值 value 不能为空]"

    try:
        # 构建批处理指令 JSON
        commands = [
            {
                "command": "set",
                "path": path,
                "props": {
                    "text": str(value)
                }
            }
        ]
        commands_str = json.dumps(commands, ensure_ascii=False)
        output = await office_cli_service.batch_update(file_path, commands_str)
        logger.info(f"✍️ [OfficeCLI Tool] 成功写盘节点 '{path}', 原位更新值: '{value}'")
        return f"成功原位写盘节点 {path} -> '{value}'"

    except Exception as e:
        logger.exception(f"✍️ [OfficeCLI Tool] 写盘节点 '{path}' 发生异常: {str(e)}")
        return f"[写盘异常: {str(e)}]"


@tool
async def officecli_add_table_row_tool(file_path: str, table_path: str, row_values_json_str: str) -> str:
    """
    [Office CLI Tool] 使用 Office CLI 为指定 Word 表格动态追加一行新数据并自动继承表格格式。

    :param file_path: Word 文档路径
    :param table_path: 目标表格的物理 Path (如 '/body/tbl[1]')
    :param row_values_json_str: 行单元格数据 JSON 数组字符串，例如 '["1", "高级工程师", "10年"]'
    :return: 执行结果描述
    """
    logger.info(f"📊 [OfficeCLI Tool] officecli_add_table_row_tool 被调用, table: '{table_path}', 行数据: {row_values_json_str}")
    if not file_path or not os.path.exists(file_path):
        return f"[错误: 目标文件不存在 {file_path}]"

    try:
        row_vals = json.loads(row_values_json_str)
        output = await office_cli_service.add_table_row(file_path, table_path, row_vals)
        logger.info(f"📊 [OfficeCLI Tool] 成功为表格 '{table_path}' 追加数据行: {row_vals}")
        return f"成功追加表格行数据到 {table_path}"
    except Exception as e:
        logger.exception(f"📊 [OfficeCLI Tool] 追加表格行异常: {str(e)}")
        return f"[追加表格行异常: {str(e)}]"


def get_all_office_cli_agent_tools() -> List[Any]:
    """获取由 Office CLI 包装供 Agent 调用的完整 Tool 列表"""
    return [
        officecli_query_structure_tool,
        officecli_write_slot_value_tool,
        officecli_add_table_row_tool,
    ]
