"""章节标题的通用归一化与兼容匹配工具。"""

import re
import unicodedata
from typing import Set


_SECTION_PREFIX_PATTERN = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零\d]+[章节部分篇]"
    r"|附[件录表图][一二三四五六七八九十\dA-Za-z]*"
    r"|[一二三四五六七八九十百零\d]+[、.]"
    r"|\([一二三四五六七八九十百零\d]+\)[、.]?"
    r")"
)


def normalize_section_title(value: object) -> str:
    """清理 Markdown 标记和空白，保留章节标题的原始语义内容。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"^[#*`~\s　]+", "", normalized)
    return re.sub(r"[\s　]+", "", normalized).strip()


def section_title_stem(value: object) -> str:
    """去除通用章节序号前缀，生成用于历史数据兼容的标题正文。"""
    stem = normalize_section_title(value)
    while stem:
        stripped = re.sub(_SECTION_PREFIX_PATTERN, "", stem, count=1)
        if stripped == stem:
            break
        stem = stripped
    return stem


def section_title_match_keys(value: object) -> Set[str]:
    """返回标题全称和正文两组匹配键。"""
    keys = {
        normalize_section_title(value),
        section_title_stem(value),
    }
    return {key for key in keys if key}
