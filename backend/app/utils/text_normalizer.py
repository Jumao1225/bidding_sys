"""结构化文本中的 HTML 实体、Markdown 和常见数学标记归一化工具。"""

import re
from html import unescape
from typing import Any


_LATEX_SYMBOLS = {
    "times": "×",
    "cdot": "·",
    "pm": "±",
    "ge": "≥",
    "le": "≤",
    "ne": "≠",
    "approx": "≈",
    "rightarrow": "→",
    "leftarrow": "←",
    "degree": "°",
    "%": "%",
}


def _replace_math_expression(match: re.Match[str]) -> str:
    """将数学包裹内容转换为可直接展示的普通文本。"""
    content = match.group(1)

    def replace_command(command_match: re.Match[str]) -> str:
        """将单个 LaTeX 命令转换为对应符号。"""
        command = command_match.group(1)
        return _LATEX_SYMBOLS.get(command, "")

    content = re.sub(r"\\([A-Za-z]+|%)", replace_command, content)
    content = content.replace("\\{", "{").replace("\\}", "}")
    content = content.replace("{", "").replace("}", "")
    return content.strip()


def normalize_markup_text(value: Any) -> Any:
    """清理结构化字段中的 HTML 实体、Markdown 加粗和常见 LaTeX 行内公式。"""
    if value is None or not isinstance(value, str):
        return value

    normalized = value
    # 兼容实体被二次转义的历史数据，但限制次数避免误伤普通文本。
    for _ in range(2):
        decoded = unescape(normalized)
        if decoded == normalized:
            break
        normalized = decoded

    # 同时清理 HTML 开始与结束标签，不影响普通的“小于数值”表达式。
    normalized = re.sub(r"</?[A-Za-z][^>]*>", " ", normalized)
    normalized = re.sub(r"\$\$(.*?)\$\$", _replace_math_expression, normalized, flags=re.DOTALL)
    normalized = re.sub(
        r"\$(?=[^$\r\n]*\\(?:[A-Za-z]+|%))([^$\r\n]+?)\$",
        _replace_math_expression,
        normalized,
    )
    normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", normalized, flags=re.DOTALL)
    return normalized.strip()
