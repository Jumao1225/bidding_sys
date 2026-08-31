"""标书日期精度格式化工具。

该模块只负责把日期时间值转换为文档展示所需的“年月日”精度，
不修改数据库中的原始时间，也不绑定任何具体项目日期。
"""

import re
from datetime import date, datetime
from typing import Any, Optional

from loguru import logger


_DATE_TIME_PATTERN = re.compile(
    r"(?P<year>\d{4})\s*(?:年|[-/])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[-/])\s*"
    r"(?P<day>\d{1,2})\s*日?\s*"
    r"(?:T|[ \t]+|(?<=日))"
    r"(?P<hour>\d{1,2})\s*(?::|：|时)\s*"
    r"(?P<minute>\d{1,2})"
    r"(?:\s*(?::|：|分)\s*(?P<second>\d{1,2}))?\s*秒?"
)

_DATE_ONLY_PATTERN = re.compile(
    r"(?P<year>\d{4})\s*(?:年|[-/])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[-/])\s*"
    r"(?P<day>\d{1,2})\s*日?"
)

_TRAILING_TIME_PATTERN = re.compile(
    r"(?<=日)\s*\d{1,2}\s*(?::|：|时)\s*\d{1,2}"
    r"(?:\s*(?::|：|分)\s*\d{1,2})?\s*秒?"
)

_DATE_SLOT_CONTEXT_PATTERN = re.compile(
    r"(?:日期|年月日|截止|开标|递交|签字|签署|落款|盖章)"
)

_TIME_LABEL_CONTEXT_PATTERN = re.compile(r"^\s*[^:：\n]{1,30}时间\s*[:：]")


def _match_to_date(match: re.Match[str]) -> Optional[date]:
    """将日期正则匹配结果安全转换为 date，非法日期返回 None。"""
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except (TypeError, ValueError) as error:
        logger.warning("日期文本解析失败，保留原值: {}，错误: {}", match.group(0), error)
        return None


def _date_to_text(value: date) -> str:
    """按标书常用中文格式输出日期，不输出时分秒。"""
    return f"{value.year}年{value.month}月{value.day}日"


def format_date_only(value: Any) -> Optional[str]:
    """把日期或日期时间值转换为仅含年月日的中文日期。

    未找到可验证的日期时返回 None，避免把未知字符串误写进标书。
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return _date_to_text(value.date())
    if isinstance(value, date):
        return _date_to_text(value)

    text = str(value).strip()
    if not text:
        return None

    for pattern in (_DATE_TIME_PATTERN, _DATE_ONLY_PATTERN):
        match = pattern.search(text)
        if not match:
            continue
        parsed_date = _match_to_date(match)
        if parsed_date is not None:
            return _date_to_text(parsed_date)

    logger.warning("无法提取有效日期，跳过日期槽位填充: {}", text[:80])
    return None


def _has_date_slot_context(*contexts: str) -> bool:
    """仅在节点原文明确表现为日期/时间槽位时启用日期精度归一化。"""
    for context in contexts:
        context_text = str(context or "")
        if _DATE_SLOT_CONTEXT_PATTERN.search(context_text):
            return True
        if _TIME_LABEL_CONTEXT_PATTERN.search(context_text):
            return True
    return False


def normalize_date_only_text(value: Any, *contexts: str) -> str:
    """将日期槽位提案中的日期时间统一降为年月日，普通正文保持不变。

    该函数只处理带日期槽位上下文的文本，避免误删技术参数、工期说明或
    普通正文中的合法时间信息。日期前过量空格同时压缩为受控间距，避免日期换行。
    """
    text = str(value or "").strip()
    if not text or not _has_date_slot_context(*contexts):
        return text

    has_date_value = bool(_DATE_TIME_PATTERN.search(text) or _DATE_ONLY_PATTERN.search(text))
    if not has_date_value:
        return text

    def replace_date(match: re.Match[str]) -> str:
        parsed_date = _match_to_date(match)
        return _date_to_text(parsed_date) if parsed_date is not None else match.group(0)

    normalized = _DATE_TIME_PATTERN.sub(replace_date, text)
    normalized = _DATE_ONLY_PATTERN.sub(replace_date, normalized)
    normalized = _TRAILING_TIME_PATTERN.sub("", normalized)
    normalized = re.sub(r"[ \t]{5,}(?=\d{4}年)", "    ", normalized)

    if normalized != text:
        logger.info("[日期精度归一化] 日期槽位仅保留年月日: '{}' -> '{}'", text[:80], normalized[:80])
    return normalized
