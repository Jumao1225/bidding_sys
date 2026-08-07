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
        err_msg = str(e)
        logger.warning(f"✍️ [OfficeCLI Tool] 写盘节点 '{path}' 提示: {err_msg}")
        if "Path not found" in err_msg:
            return f"[提示: 目标 Path '{path}' 尚不存在。若是表格节点，请改用 officecli_fill_table_rows 工具从第二行开始批量填充表格，会自动为您追加并对齐表格行！]"
        return f"[写盘异常: {err_msg}]"


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
        row_vals = json.loads(row_values_json_str) if isinstance(row_values_json_str, str) else row_values_json_str
        if not isinstance(row_vals, list):
            return "[错误: row_values_json_str 必须为 JSON 列表]"

        cmds = [{"command": "add", "parent": table_path, "type": "row"}]
        for col_idx, val in enumerate(row_vals):
            cmds.append({
                "command": "set",
                "path": f"{table_path}/row[last()]/cell[{col_idx + 1}]",
                "props": {"text": str(val)}
            })

        output = await office_cli_service.apply_batch(file_path, cmds)
        logger.info(f"📊 [OfficeCLI Tool] 成功为表格 '{table_path}' 追加数据行: {row_vals}")
        return f"成功追加表格行数据到 {table_path}"
    except Exception as e:
        logger.exception(f"📊 [OfficeCLI Tool] 追加表格行异常: {str(e)}")
        return f"[追加表格行异常: {str(e)}]"


@tool
async def officecli_batch_fill_sentence_tool(file_path: str, updates_json_str: str) -> str:
    """
    [Office CLI Tool] 批量原子化更新 Word 文档中的多个长句段落槽位。
    适用于在收集完完整信息后，一次性提交多个段落/句子的替换，避免多次写盘与格式错乱。

    :param file_path: 待修改 Word 文档路径
    :param updates_json_str: JSON 数组字符串，格式如：
        '[{"path": "/body/p[2]", "value": "公司名称：XXX有限公司"}, {"path": "/body/p[5]", "value": "注册资金：XXX万元"}]'
    :return: 执行结果描述
    """
    logger.info(f"📝 [OfficeCLI Tool] officecli_batch_fill_sentence_tool 被调用, file: '{file_path}'")
    if not file_path or not os.path.exists(file_path):
        return f"[错误: 目标文件不存在 {file_path}]"
    if not updates_json_str:
        return "[错误: 批处理更新指令 updates_json_str 不能为空]"

    try:
        items = json.loads(updates_json_str) if isinstance(updates_json_str, str) else updates_json_str
        if not isinstance(items, list):
            return "[错误: updates_json_str 必须为 JSON 列表]"

        commands = []
        for item in items:
            p_path = item.get("path")
            val = item.get("value", "")
            if p_path:
                commands.append({
                    "command": "set",
                    "path": p_path,
                    "props": {"text": str(val)}
                })

        if not commands:
            return "[提示: 没有有效的写盘指令执行]"

        commands_str = json.dumps(commands, ensure_ascii=False)
        output = await office_cli_service.batch_update(file_path, commands_str)
        logger.info(f"📝 [OfficeCLI Tool] 成功原子批处理更新 {len(commands)} 个段落槽位")
        return f"成功原子更新 {len(commands)} 个段落槽位数据"
    except Exception as e:
        logger.exception(f"📝 [OfficeCLI Tool] 批处理更新段落异常: {str(e)}")
        return f"[批处理更新异常: {str(e)}]"


@tool
async def officecli_fill_table_rows_tool(
    file_path: str,
    table_path: str,
    rows_json_str: str,
    auto_index: bool = True
) -> str:
    """
    [Office CLI Tool] 批量向指定 Word 表格中填充/追加数据行。
    严格保持表头行 (row 1) 不动；从 Row 2 开始优先覆盖填充模板自带的空白行，行数不足时自动追加新行。
    当 auto_index=True 时自动在第一列填入连续递增序号 (1, 2, 3...)。

    :param file_path: Word 文档路径
    :param table_path: 表格 Path (如 '/body/tbl[1]')
    :param rows_json_str: 二维数组 JSON 字符串，包含所有需追加的行数据列表。
        例如：'[["岗位A", "人员A", "证书A"], ["岗位B", "人员B", "证书B"]]'
    :param auto_index: 是否自动在第一列生成 1..N 递增序号 (默认 True)
    :return: 执行结果描述
    """
    logger.info(f"📊 [OfficeCLI Tool] officecli_fill_table_rows_tool 被调用, table: '{table_path}'")
    if not file_path or not os.path.exists(file_path):
        return f"[错误: 目标文件不存在 {file_path}]"
    if not table_path or not rows_json_str:
        return "[错误: table_path 与 rows_json_str 不能为空]"

    try:
        raw_rows = json.loads(rows_json_str) if isinstance(rows_json_str, str) else rows_json_str
        if not isinstance(raw_rows, list):
            return "[错误: rows_json_str 必须为二维 JSON 列表]"

        # 1. 查询表格现有 DOM 节点，正则精准解析表格现有 rows=N 行数
        existing_row_count = 1  # 默认至少包含 1 行表头
        try:
            import re
            struct_str = await office_cli_service.query_structure(file_path, "table")
            for line in str(struct_str).split("\n"):
                if table_path in line:
                    m = re.search(r'rows=(\d+)', line) or re.search(r'children=(\d+)', line)
                    if m:
                        existing_row_count = int(m.group(1))
                        logger.info(f"📊 [OfficeCLI Tool] 成功识别到表格 '{table_path}' 现有行数: {existing_row_count}")
                        break
        except Exception as err:
            logger.warning(f"📊 [OfficeCLI Tool] 查询表格结构统计行数异常: {err}")

        cmds = []
        added_count = 0
        for i, row in enumerate(raw_rows):
            if not isinstance(row, list):
                continue
            row_data = list(row)
            if auto_index:
                # 检查第一列是否已是纯数字序号，若不是则注入递增序号
                if not (row_data and str(row_data[0]).isdigit() and int(row_data[0]) == i + 1):
                    row_data.insert(0, str(i + 1))
            
            # Row 1 为表头；数据行目标行号为 target_row_idx = i + 2
            target_row_idx = i + 2
            if target_row_idx <= existing_row_count:
                # 优先原位覆盖模板中表头下方已有的空白行 (Row 2, Row 3...)
                target_row_path = f"{table_path}/row[{target_row_idx}]"
                for col_idx, val in enumerate(row_data):
                    cmds.append({
                        "command": "set",
                        "path": f"{target_row_path}/cell[{col_idx + 1}]",
                        "props": {"text": str(val)}
                    })
            else:
                # 超出模板已有行数时，自动追加新行
                cmds.append({"command": "add", "parent": table_path, "type": "row"})
                for col_idx, val in enumerate(row_data):
                    cmds.append({
                        "command": "set",
                        "path": f"{table_path}/row[last()]/cell[{col_idx + 1}]",
                        "props": {"text": str(val)}
                    })
            added_count += 1

        # 2. 自动清理模板中余下的未用预设空行（从底部向上倒序删除，防止留白与多余空行）
        last_filled_row_idx = added_count + 1
        if last_filled_row_idx < existing_row_count:
            for r in range(existing_row_count, last_filled_row_idx, -1):
                cmds.append({"command": "remove", "path": f"{table_path}/row[{r}]"})

        if cmds:
            await office_cli_service.apply_batch(file_path, cmds)

        logger.info(f"📊 [OfficeCLI Tool] 成功为表格 '{table_path}' 填充 {added_count} 行数据（已防留白）")
        return f"成功为表格 {table_path} 从第二行开始填充 {added_count} 行数据（表头完好，已有空行原位覆盖对齐）"
    except Exception as e:
        logger.exception(f"📊 [OfficeCLI Tool] 批量填充表格行异常: {str(e)}")
        return f"[批量填充表格行异常: {str(e)}]"



def get_all_office_cli_agent_tools() -> List[Any]:
    """获取由 Office CLI 包装供 Agent 调用的完整 Tool 列表"""
    return [
        officecli_query_structure_tool,
        officecli_write_slot_value_tool,
        officecli_add_table_row_tool,
        officecli_batch_fill_sentence_tool,
        officecli_fill_table_rows_tool,
    ]

