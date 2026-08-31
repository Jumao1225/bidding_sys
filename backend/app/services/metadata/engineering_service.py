from __future__ import annotations

import logging
import json
import os
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import BaseMetadataService
from app.db.models.metadata import EngineeringMetadata
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


def _schema_to_log_json(schema: BaseModel) -> str:
    """将结构化模型结果序列化为可检索的中文 JSON 日志文本。"""
    try:
        if hasattr(schema, "model_dump"):
            payload = schema.model_dump(mode="json")
        else:
            payload = schema.dict()
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError) as exc:
        logger.exception("结构化模型结果序列化失败，将记录字符串兜底值：{}", exc)
        return str(schema)


@dataclass(frozen=True)
class _SourceTableRow:
    """MinerU 表格中的可用于结构对齐的原始行。"""

    table_index: int
    row_index: int
    item_code: str
    item_name: str
    specifications: Optional[str]
    unit: Optional[str]
    quantity: Optional[float]


class _EngineeringTableParser(HTMLParser):
    """解析工程清单 HTML 表格，并展开跨行、跨列单元格。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[tuple[str, int, int]]] | None = None
        self._current_row: list[tuple[str, int, int]] | None = None
        self._current_cell: list[str] | None = None
        self._current_rowspan = 1
        self._current_colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录表格、行和单元格的开始。"""
        normalized_tag = tag.lower()
        if normalized_tag == "table":
            self._current_table = []
        elif normalized_tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif normalized_tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            attrs_map = dict(attrs)
            self._current_rowspan = self._parse_span(attrs_map.get("rowspan"))
            self._current_colspan = self._parse_span(attrs_map.get("colspan"))

    def handle_data(self, data: str) -> None:
        """收集单元格文本，保留原始内容但折叠展示空白。"""
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """结束单元格、行或表格并写入解析结果。"""
        normalized_tag = tag.lower()
        if normalized_tag in {"td", "th"} and self._current_row is not None:
            if self._current_cell is None:
                self._current_row.append(("", self._current_rowspan, self._current_colspan))
            else:
                cell_text = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
                self._current_row.append(
                    (cell_text, self._current_rowspan, self._current_colspan)
                )
            self._current_cell = None
            self._current_rowspan = 1
            self._current_colspan = 1
        elif normalized_tag == "tr" and self._current_table is not None:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif normalized_tag == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._expand_table(self._current_table))
            self._current_table = None

    @staticmethod
    def _parse_span(value: str | None) -> int:
        """读取 HTML 跨行/跨列属性，异常值按单格处理。"""
        if not value:
            return 1
        try:
            return max(int(value), 1)
        except ValueError:
            logger.warning("[EngineeringService] HTML 表格 span 属性无效，已按 1 处理：值=%s", value)
            return 1

    @staticmethod
    def _expand_table(
        raw_rows: list[list[tuple[str, int, int]]],
    ) -> list[list[str]]:
        """将 HTML 跨行/跨列单元格展开为稳定的逻辑列网格。"""
        occupied: dict[tuple[int, int], str] = {}
        max_column = 0
        for row_index, raw_row in enumerate(raw_rows):
            column_index = 0
            for cell_text, row_span, col_span in raw_row:
                while (row_index, column_index) in occupied:
                    column_index += 1
                for row_offset in range(row_span):
                    for column_offset in range(col_span):
                        occupied[(row_index + row_offset, column_index + column_offset)] = cell_text
                column_index += col_span
                max_column = max(max_column, column_index)

        return [
            [occupied.get((row_index, column_index), "") for column_index in range(max_column)]
            for row_index in range(len(raw_rows))
        ]


def _normalize_source_cell(value: Optional[str]) -> str:
    """归一化原始表格单元格，便于跨 OCR 空白差异进行匹配。"""
    if not value:
        return ""
    return re.sub(r"\s+", "", unescape(value)).strip()


def _parse_source_quantity(value: Optional[str]) -> Optional[float]:
    """只解析单元格中明确写出的纯数字数量。"""
    normalized = (value or "").strip().replace(",", "")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return None
    return float(normalized)


def _find_source_header_index(header_cells: list[str], keywords: tuple[str, ...]) -> Optional[int]:
    """按表头语义定位列号，兼容不同清单的列顺序。"""
    for index, cell in enumerate(header_cells):
        normalized_cell = _normalize_source_cell(cell)
        if any(keyword in normalized_cell for keyword in keywords):
            return index
    return None


def _is_section_marker_code(value: str) -> bool:
    """识别表格中独立的括号分组编码，不依赖具体行业或项目名称。"""
    return bool(re.fullmatch(r"[（(]\s*[^（）()\s]{1,8}\s*[）)]", value.strip()))


def _is_plain_child_code(value: str) -> bool:
    """识别分组下的普通整数明细编码。"""
    return bool(re.fullmatch(r"\d+", value.strip()))


def _source_rows_from_context(context: str) -> list[list[_SourceTableRow]]:
    """从模型实际上下文中提取表格行，供结果层做结构性对齐。"""
    parser = _EngineeringTableParser()
    parser.feed(context)
    parsed_tables: list[list[_SourceTableRow]] = []
    for table_index, table in enumerate(parser.tables):
        header_cells = table[0] if table else []
        code_index = _find_source_header_index(header_cells, ("序号", "编码", "编号"))
        name_index = _find_source_header_index(header_cells, ("设备名称", "材料名称", "货物名称", "项目名称", "名称"))
        specification_index = _find_source_header_index(header_cells, ("规格型号", "型号规格", "规格", "型号", "描述", "参数"))
        unit_index = _find_source_header_index(header_cells, ("单位",))
        quantity_index = _find_source_header_index(header_cells, ("数量", "工程量", "用量"))
        code_index = 0 if code_index is None else code_index
        name_index = 1 if name_index is None else name_index
        parsed_rows: list[_SourceTableRow] = []
        for row_index, cells in enumerate(table):
            if row_index == 0:
                # 每张候选清单表的首行是表头，不允许兜底逻辑把“序号/名称”生成清单项。
                continue
            if len(cells) <= max(code_index, name_index):
                continue
            item_code = cells[code_index].strip()
            item_name = cells[name_index].strip()
            if not item_code or not item_name:
                continue

            # 根据当前表头读取规格、单位和数量，兼容数量列位于末尾等表格变体。
            # 这里仅依据表格列结构读取，不使用项目名称或业务关键词。
            specifications = (
                cells[specification_index].strip()
                if specification_index is not None and specification_index < len(cells)
                else None
            )
            unit = (
                cells[unit_index].strip()
                if unit_index is not None and unit_index < len(cells)
                else None
            )
            quantity = _parse_source_quantity(
                cells[quantity_index] if quantity_index is not None and quantity_index < len(cells) else None
            )
            parsed_rows.append(
                _SourceTableRow(
                    table_index=table_index,
                    row_index=row_index,
                    item_code=item_code,
                    item_name=item_name,
                    specifications=specifications,
                    unit=unit,
                    quantity=quantity,
                )
            )
        if parsed_rows:
            parsed_tables.append(parsed_rows)
    return parsed_tables


def _assign_items_to_source_tables(
    items: list["EquipmentItem"],
    source_tables: list[list[_SourceTableRow]],
) -> tuple[dict[int, int], set[int]]:
    """按原始表格行将模型项映射到表格，避免相同编码跨表混用。

    该映射仅用于后处理，不会写入对外返回的清单字段。匹配时优先使用编码、
    名称、规格和单位，剩余无法定位的模型项由调用方作为未归属项处理。
    """
    def item_key(value: Optional[str]) -> str:
        """统一模型字段与原始单元格中的空白及 HTML 实体。"""
        return _normalize_source_cell(value)

    assignments: dict[int, int] = {}
    unassigned_indexes = set(range(len(items)))

    for table_rows in source_tables:
        if not table_rows:
            continue
        # 使用解析器保留的原始表格编号，避免空表被过滤后导致编号错位。
        table_index = table_rows[0].table_index
        for source_row in table_rows:
            source_code = item_key(source_row.item_code)
            source_name = item_key(source_row.item_name)
            source_specification = item_key(source_row.specifications)
            source_unit = item_key(source_row.unit)
            candidates: list[tuple[int, int]] = []
            for item_index in unassigned_indexes:
                item = items[item_index]
                if item_key(item.item_name) != source_name:
                    continue
                model_code = item_key(item.item_code)
                if model_code and source_code and model_code != source_code:
                    continue
                score = 20 if model_code and model_code == source_code else 0
                if source_specification and item_key(item.specifications) == source_specification:
                    score += 10
                if source_unit and item_key(item.unit) == source_unit:
                    score += 5
                if source_row.quantity is not None and item.quantity == source_row.quantity:
                    score += 3
                candidates.append((score, item_index))
            if not candidates:
                continue
            _, selected_index = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))
            assignments[selected_index] = table_index
            unassigned_indexes.remove(selected_index)

    return assignments, unassigned_indexes


def _get_engineering_context_limit() -> int:
    """读取工程清单单次模型上下文上限，允许部署环境按模型窗口调整。"""
    raw_limit = os.getenv("ENGINEERING_CONTEXT_MAX_CHARS", "60000")
    try:
        limit = int(raw_limit)
    except ValueError:
        logger.warning(
            "[EngineeringService] ENGINEERING_CONTEXT_MAX_CHARS 配置无效，将使用默认上下文上限。"
        )
        return 60000
    return max(limit, 1000)


def _get_engineering_source_row_limit() -> int:
    """读取单次模型上下文允许承载的原始清单行数上限。"""
    raw_limit = os.getenv("ENGINEERING_MAX_SOURCE_ROWS_PER_CONTEXT", "160")
    try:
        limit = int(raw_limit)
    except ValueError:
        logger.warning(
            "[EngineeringService] ENGINEERING_MAX_SOURCE_ROWS_PER_CONTEXT 配置无效，"
            "将使用默认原始行数上限。"
        )
        return 160
    return max(limit, 10)


def _count_table_data_rows(table_content: str) -> int:
    """统计表格数据行数量，不把表头计入输出风险估算。"""
    if re.search(r"<table", table_content, re.IGNORECASE):
        return max(len(re.findall(r"<tr[\s\S]*?</tr>", table_content, re.IGNORECASE)) - 1, 0)
    lines = [line for line in table_content.splitlines() if line.strip()]
    return max(len(lines) - 2, 0)


def _split_table_preserving_rows(
    table_content: str,
    max_chars: int,
    max_rows: Optional[int] = None,
) -> list[str]:
    """按完整数据行拆分超长表格，并在每个分块中保留原表头。"""
    if len(table_content) <= max_chars:
        if max_rows is None or _count_table_data_rows(table_content) <= max_rows:
            return [table_content]

    if re.search(r"<table", table_content, re.IGNORECASE):
        rows = re.findall(r"<tr[\s\S]*?</tr>", table_content, re.IGNORECASE)
        if len(rows) <= 1:
            return [table_content]
        header = rows[0]
        chunks: list[str] = []
        current_rows = [header]
        current_length = len(header)
        for row in rows[1:]:
            current_data_rows = len(current_rows) - 1
            exceeds_char_limit = current_length + len(row) + 20 > max_chars
            exceeds_row_limit = max_rows is not None and current_data_rows >= max_rows
            if len(current_rows) > 1 and (exceeds_char_limit or exceeds_row_limit):
                chunks.append("<table>\n" + "\n".join(current_rows) + "\n</table>")
                current_rows = [header]
                current_length = len(header)
            current_rows.append(row)
            current_length += len(row) + 1
        if len(current_rows) > 1:
            chunks.append("<table>\n" + "\n".join(current_rows) + "\n</table>")
        return chunks or [table_content]

    lines = [line for line in table_content.splitlines() if line.strip()]
    if len(lines) <= 2:
        return [table_content]
    header_lines = lines[:2]
    chunks = []
    current_lines = list(header_lines)
    current_length = sum(len(line) + 1 for line in current_lines)
    for line in lines[2:]:
        current_data_rows = len(current_lines) - 2
        exceeds_char_limit = current_length + len(line) + 1 > max_chars
        exceeds_row_limit = max_rows is not None and current_data_rows >= max_rows
        if len(current_lines) > 2 and (exceeds_char_limit or exceeds_row_limit):
            chunks.append("\n".join(current_lines))
            current_lines = list(header_lines)
            current_length = sum(len(item) + 1 for item in current_lines)
        current_lines.append(line)
        current_length += len(line) + 1
    if len(current_lines) > 2:
        chunks.append("\n".join(current_lines))
    return chunks or [table_content]


def _split_text_preserving_paragraphs(text: str, max_chars: int) -> list[str]:
    """按段落和句子边界拆分普通文本，避免超长上下文被硬截断。"""
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            sentences = [item.strip() for item in re.split(r"(?<=[。！？!?；;])\s*", paragraph) if item.strip()]
        else:
            sentences = [paragraph]
        for sentence in sentences:
            if current_parts and current_length + len(sentence) + 2 > max_chars:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_length = 0
            current_parts.append(sentence)
            current_length += len(sentence) + (2 if current_parts else 0)

    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return chunks or [text]


def _build_semantic_engineering_chunks(
    clean_context: str,
    table_matches: list[re.Match[str]],
    max_chars: int,
) -> tuple[list[str], list[Optional[str]]]:
    """优先整体提交清单上下文，超限时按完整表格和标题边界聚合拆分。"""
    if not clean_context:
        return [], []
    source_row_limit = _get_engineering_source_row_limit()
    total_source_rows = sum(
        _count_table_data_rows(table_match.group(0))
        for table_match in table_matches
    )
    row_pressure = bool(table_matches) and total_source_rows > source_row_limit
    if len(clean_context) <= max_chars and not row_pressure:
        section_titles: list[Optional[str]] = []
        last_end = 0
        for table_match in table_matches:
            heading = clean_context[last_end:table_match.start()].strip()
            section_titles.append(extract_engineering_section_name_from_heading(heading))
            last_end = table_match.end()
        unique_sections = {item for item in section_titles if item}
        shared_section = next(iter(unique_sections)) if len(unique_sections) == 1 else None
        return [clean_context], [shared_section]
    if not table_matches:
        text_chunks = _split_text_preserving_paragraphs(clean_context, max_chars)
        return text_chunks, [None] * len(text_chunks)

    units: list[tuple[str, Optional[str], int]] = []
    last_end = 0
    for table_match in table_matches:
        # 表格前的标题、说明和上一张表格后的局部正文属于当前表格的语义上下文，
        # 必须与表格绑定后再参与分块，不能先把表格单独切走。
        heading = clean_context[last_end:table_match.start()].strip()
        table_content = table_match.group(0)
        section_title = extract_engineering_section_name_from_heading(heading)
        table_parts = _split_table_preserving_rows(
            table_content,
            max_chars,
            max_rows=source_row_limit,
        )
        for part_index, table_part in enumerate(table_parts):
            # 单张表格按数据行拆分时，每个子块都重复表头和同一份局部上下文，
            # 保证模型不会拿到失去章节归属的孤立表格行。
            unit_prefix = heading
            unit_text = f"{unit_prefix}\n\n{table_part}".strip()
            units.append((unit_text, section_title, _count_table_data_rows(table_part)))
        last_end = table_match.end()

    tail = clean_context[last_end:].strip()
    if tail:
        units.extend(
            (part, None, 0)
            for part in _split_text_preserving_paragraphs(tail, max_chars)
        )

    chunks: list[str] = []
    chunk_sections: list[Optional[str]] = []
    current_parts: list[str] = []
    current_sections: list[Optional[str]] = []
    current_length = 0
    current_source_rows = 0

    for unit_text, section_title, source_row_count in units:
        separator_length = 2 if current_parts else 0
        exceeds_char_limit = current_length + separator_length + len(unit_text) > max_chars
        exceeds_row_limit = (
            current_parts
            and current_source_rows + source_row_count > source_row_limit
        )
        if current_parts and (exceeds_char_limit or exceeds_row_limit):
            chunks.append("\n\n".join(current_parts))
            unique_sections = {item for item in current_sections if item}
            chunk_sections.append(next(iter(unique_sections)) if len(unique_sections) == 1 else None)
            current_parts = []
            current_sections = []
            current_length = 0
            current_source_rows = 0
        current_parts.append(unit_text)
        current_sections.append(section_title)
        current_length += separator_length + len(unit_text)
        current_source_rows += source_row_count

    if current_parts:
        chunks.append("\n\n".join(current_parts))
        unique_sections = {item for item in current_sections if item}
        chunk_sections.append(next(iter(unique_sections)) if len(unique_sections) == 1 else None)

    return chunks, chunk_sections


def _build_table_scoped_engineering_chunks(
    clean_context: str,
    table_matches: list[re.Match[str]],
    max_chars: int,
) -> tuple[list[str], list[Optional[str]], list[int]]:
    """按原始表格边界构造上下文，保留每个分块对应的表格编号。

    多张清单表经常重复使用 1、1.1 等编码。将不同表格合并后，模型结果无法
    可靠回写到原始表格，后续层级修复也容易发生跨表串挂。因此每张表都独立
    进入模型，同时保留表格索引供后处理使用。
    """
    if not clean_context or not table_matches:
        return [], [], []

    chunks: list[str] = []
    chunk_sections: list[Optional[str]] = []
    chunk_table_indexes: list[int] = []
    last_end = 0

    for table_index, table_match in enumerate(table_matches):
        heading = clean_context[last_end:table_match.start()].strip()
        section_title = extract_engineering_section_name_from_heading(heading)
        table_parts = _split_table_preserving_rows(
            table_match.group(0),
            max_chars,
            max_rows=_get_engineering_source_row_limit(),
        )
        for table_part in table_parts:
            chunk_text = f"{heading}\n\n{table_part}".strip()
            chunks.append(chunk_text)
            chunk_sections.append(section_title)
            chunk_table_indexes.append(table_index)
        last_end = table_match.end()

    return chunks, chunk_sections, chunk_table_indexes


def normalize_engineering_section_name(raw_title: Optional[str]) -> Optional[str]:
    """按通用标题结构清理所属分项名称，不绑定任何具体项目标题。"""
    if not raw_title or not isinstance(raw_title, str):
        return None

    title = _strip_section_name_style_markers(raw_title)
    if not title:
        return None

    # 对“任意包装标题（语义分项）”统一取括号内语义，不依赖固定项目名称或固定标题前缀。
    matched = re.fullmatch(r"(.{1,40}?)\s*[（(]([^（）()]+)[）)]", title)
    if matched:
        wrapper = matched.group(1).strip()
        semantic_name = matched.group(2).strip()
        if wrapper and semantic_name and not re.search(r"[，,。；;！？!?：:]", wrapper):
            return semantic_name
    return title


def _strip_section_name_style_markers(raw_title: str) -> str:
    """仅清除所属分项名称中的 Markdown/HTML 样式标记，保留业务文本和单个星号参数。"""
    # 这里只处理 section_name 的候选标题，不能对整段表格上下文做 HTML 清洗，
    # 否则会破坏后续表格边界识别及规格参数中的原文符号。
    style_tag_pattern = re.compile(
        r"</?(?:span|strong|b|em|i|u|font|s|strike|del|mark)\b[^>]*>",
        re.IGNORECASE,
    )
    cleaned_title = style_tag_pattern.sub("", raw_title)
    # 连续星号是 Markdown 加粗/字体标记；单个星号可能是技术参数或乘号，必须保留。
    cleaned_title = re.sub(r"\*{2,}", "", cleaned_title)
    cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
    if cleaned_title != raw_title.strip():
        logger.debug(
            "[EngineeringService] 已清除 section_name 样式标记：清洗前长度=%d，清洗后长度=%d",
            len(raw_title.strip()),
            len(cleaned_title),
        )
    return cleaned_title


def extract_engineering_section_name_from_heading(heading_text: str) -> Optional[str]:
    """从表格前置标题中提取最近的语义分区，不把章节或表格包装标题当分区。

    提取顺序完全依据标题层级和文本结构：优先选择阿拉伯序号的局部分区，
    其次使用清单标题中的括号语义，最后才回退到其它明确标题，不依赖项目名称映射。
    """
    if not heading_text:
        return None

    lines = [line.strip() for line in heading_text.split("\n") if line.strip()]
    semantic_candidates: list[str] = []
    table_wrapper_candidates: list[str] = []
    segment_heading_candidates: list[str] = []

    for line in reversed(lines):
        clean_line = re.sub(r"^[#\s*]+", "", line).strip()
        if not clean_line or re.match(r"^(?:注|说明|备注|提示|注意)[:：]", clean_line):
            continue

        # 去除标题后面的“以下清单/说明”等导语，但保留标题主体。
        title = re.split(
            r"[-—–]{1,}|——|—以下|：以下|:以下|；以下|;\s*以下|注[:：]|说明[:：]|（以下",
            clean_line,
        )[0].strip()
        title_clean = re.sub(r"^[0-9]+[、.．]\s*", "", title).strip()
        normalized_title = normalize_engineering_section_name(title_clean or title)
        if not normalized_title or len(normalized_title) < 2:
            continue

        starts_local_number = bool(re.match(r"^[0-9]+[、.．]", clean_line))
        starts_broad_number = bool(
            re.match(r"^(?:[一二三四五六七八九十百]+[、.．]|第[0-9一二三四五六七八九十百]+[标段章节部分区])", clean_line)
        )
        # 这些是表格/清单的包装标题，不是实际区域；括号内的语义部分可作为回退值。
        is_table_wrapper = bool(
            re.search(r"清单|报价|货物需求|设备材料|一览表", title_clean)
        )

        if starts_local_number and not is_table_wrapper:
            semantic_candidates.append(normalized_title)
        elif is_table_wrapper:
            # 只有括号中确实提取出语义名称时，才将清单标题作为回退值。
            if normalized_title != title_clean:
                table_wrapper_candidates.append(normalized_title)
        elif starts_broad_number and re.search(r"标段|分标|区域|分项|部分|地块|厂区|工区|工业|园区|系统", title_clean):
            # 中文大序号只有在标题本身明确表达分区/标段语义时才保留。
            segment_heading_candidates.append(normalized_title)
        elif (
            not starts_broad_number
            and len(normalized_title) <= 40
            and re.search(r"标段|分标|区域|分项|部分|地块|厂区|工区|工业|园区|系统", normalized_title)
            and not re.search(r"[，,。；;！？!?：:]", normalized_title)
        ):
            # 部分文档的局部分区标题不带序号，例如“某工业四区”；仅接受短标题结构，避免正文误识别。
            segment_heading_candidates.append(normalized_title)

    if semantic_candidates:
        return semantic_candidates[0]
    if table_wrapper_candidates:
        return table_wrapper_candidates[0]
    if segment_heading_candidates:
        return segment_heading_candidates[0]
    return None


def _has_explicit_table_measurement(cells: list[str]) -> bool:
    """依据表格行的多列计量载荷判断是否为明确计量行，不枚举具体单位。"""
    if len(cells) < 3:
        return False
    has_numeric_value = any(
        bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell.replace(",", "")))
        for cell in cells[2:]
    )
    non_empty_payload_cells = sum(bool(cell.strip()) for cell in cells[2:])
    return has_numeric_value and non_empty_payload_cells >= 2


def _extract_inner_section_candidates(table_content: str) -> list[tuple[str, str]]:
    """从当前表格结构中找出括号分组及带递进子项的分类行，不依赖具体项目名称。"""
    if not table_content or not re.search(r"<table", table_content, flags=re.IGNORECASE):
        return []

    parser = _EngineeringTableParser()
    parser.feed(table_content)
    if not parser.tables:
        return []

    rows = parser.tables[0]
    candidates: list[tuple[str, str]] = []
    for row_index, cells in enumerate(rows):
        if len(cells) < 2:
            continue
        code = cells[0].strip()
        name = cells[1].strip()
        if not code or not name:
            continue

        if _is_section_marker_code(code):
            candidates.append((code, name))
            continue

        if not _is_plain_child_code(code) or _has_explicit_table_measurement(cells):
            continue

        has_recursive_child = any(
            next_code.startswith(f"{code}.")
            for next_row in rows[row_index + 1:]
            if len(next_row) >= 1
            for next_code in [next_row[0].strip()]
        )
        if has_recursive_child:
            candidates.append((code, name))
    return candidates


def build_engineering_table_section_hints(
    clean_context: str,
    table_matches: list[re.Match[str]],
) -> list[str]:
    """为每张清单表生成由原文标题推导的分区定位提示，避免多表上下文互相串区。"""
    if not clean_context or not table_matches:
        return []

    hints: list[str] = []
    last_end = 0
    for table_index, table_match in enumerate(table_matches, start=1):
        heading = clean_context[last_end:table_match.start()].strip()
        section_name = extract_engineering_section_name_from_heading(heading)
        if section_name:
            # 仅传递当前表格前的真实原文，模型必须从该证据中作最终判断。
            heading_lines = [line.strip() for line in heading.splitlines() if line.strip()]
            evidence = next(
                (line for line in reversed(heading_lines) if section_name in line),
                section_name,
            )
            hint = f"- 表格 {table_index}：外层候选分区={section_name}；原文标题证据={evidence}"
        else:
            hint = f"- 表格 {table_index}：未从表格前置标题确认分区，必须返回 null 或依据表内独立分区文字判断"

        inner_candidates = _extract_inner_section_candidates(table_match.group(0))
        if inner_candidates:
            inner_text = "；".join(
                f"编码 {code} / 名称 {name}"
                for code, name in inner_candidates
            )
            hint += (
                f"\n  表内更具体分组候选（仅用于识别 parent_item/root_item/tree_level，不得覆盖 section_name）：{inner_text}"
            )
        hints.append(hint)
        last_end = table_match.end()
    return hints


def is_engineering_document_chapter_title(section_name: Optional[str]) -> bool:
    """判断字段是否为中文大章/“第X章”格式的文档章节标题。"""
    if not section_name or not isinstance(section_name, str):
        return False
    return bool(
        re.match(
            r"^(?:[一二三四五六七八九十百千万]+[、.．]|第[0-9一二三四五六七八九十百千万]+[章节篇部分])",
            section_name.strip(),
        )
    )


def is_valid_engineering_section_name(section_name: Optional[str]) -> bool:
    """按通用文本结构校验分区字段，拒绝正文长句和完整条款。"""
    if not section_name or not isinstance(section_name, str):
        return False

    value = section_name.strip()
    if not value or len(value) > 40 or "\n" in value:
        return False
    if is_engineering_document_chapter_title(value):
        return False
    # 分区标题允许使用“、”和逗号连接并列名称，例如“动力、照明”；
    # 仅将句号、分号、感叹号、问号和冒号视为完整正文句子的信号。
    return not bool(re.search(r"[。；;！？!?：:]", value))


def _compact_section_evidence_text(value: object) -> str:
    """压缩证据文本中的空白，兼容 HTML、Markdown 和模型换行差异。"""
    return re.sub(r"\s+", "", str(value or "")).strip()


def _extract_section_evidence_lines(context: str) -> list[str]:
    """提取标题行和表格行，作为所属分区原文证据的核验范围。"""
    if not context:
        return []

    evidence_lines = [
        line.strip()
        for line in context.splitlines()
        if line.strip() and not re.search(r"<(?:table|tr|td|th)\b", line, flags=re.IGNORECASE)
    ]
    # HTML 表格经常被压缩成单行，单独拆出每个 tr，避免整张表无法定位证据行。
    for row_match in re.finditer(r"<tr[\s\S]*?</tr>", context, flags=re.IGNORECASE):
        row_text = unescape(re.sub(r"<[^>]+>", " ", row_match.group(0)))
        row_text = re.sub(r"\s+", " ", row_text).strip()
        if row_text:
            evidence_lines.append(row_text)
    return evidence_lines


def _evidence_appears_in_data_row(context: str, evidence: str) -> bool:
    """判断分区证据是否实际来自带编码或计量信息的表格数据行。"""
    compact_evidence = _compact_section_evidence_text(evidence)
    if not compact_evidence:
        return False

    for row_match in re.finditer(r"<tr[\s\S]*?</tr>", context, flags=re.IGNORECASE):
        row_html = row_match.group(0)
        cells = [
            _compact_section_evidence_text(unescape(re.sub(r"<[^>]+>", " ", cell)))
            for cell in re.findall(r"<t[dh][^>]*>[\s\S]*?</t[dh]>", row_html, flags=re.IGNORECASE)
        ]
        if compact_evidence not in _compact_section_evidence_text(row_html) or len(cells) < 2:
            continue

        has_source_code = bool(
            re.fullmatch(
                r"(?:\(?[一二三四五六七八九十百千万]+\)?|\(?\d+(?:\.\d+)*\)?)[、.．]?",
                cells[0],
            )
        )
        has_numeric_measurement = any(
            bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell.replace(",", "")))
            for cell in cells[2:]
        )
        non_empty_payload_cells = sum(bool(cell.strip()) for cell in cells[2:])
        if has_source_code and has_numeric_measurement and non_empty_payload_cells >= 2:
            return True

    return False


def validate_engineering_section_evidence(
    item: "EquipmentItem",
    context: str,
    known_item_names: Optional[set[str]] = None,
) -> bool:
    """验证模型返回的分区是否有原文证据且不是设备行自身。"""
    section_name = _compact_section_evidence_text(item.section_name)
    evidence = _compact_section_evidence_text(item.section_evidence)
    item_name = _compact_section_evidence_text(item.item_name)
    if not section_name or not evidence or not item_name:
        return False
    if section_name not in evidence:
        return False
    if section_name == item_name or evidence == item_name:
        return False

    # 若分区名本身也是当前清单中的设备/父级名称，且证据来自计价数据行，
    # 则优先按设备名称误识别处理；真正的分区标题应来自标题行或独立分区行。
    compact_item_names = {
        _compact_section_evidence_text(name)
        for name in (known_item_names or set())
        if name
    }
    if section_name in compact_item_names and _evidence_appears_in_data_row(context, evidence):
        return False

    # MinerU 的 HTML 单元格之间存在 </td><td> 标签，不能直接在原始 HTML
    # 字符串中查找“(一)分区名称”。必须在去除标签后的标题/表格行中核验。
    compact_evidence_lines = [
        _compact_section_evidence_text(line)
        for line in _extract_section_evidence_lines(context)
    ]
    if not any(evidence in line for line in compact_evidence_lines):
        return False

    # 如果证据与设备名称出现在同一原文行，说明模型很可能拿设备行充当分区依据。
    for source_line in _extract_section_evidence_lines(context):
        compact_line = _compact_section_evidence_text(source_line)
        if evidence in compact_line and item_name in compact_line:
            return False
    return True


class EquipmentItem(BaseModel):
    """设备/软件/材料清单明细（支持生成技术偏离表与多级精细化 BOM 成本核算）"""
    # 禁止模型返回未定义字段，避免字段名写错后被静默丢弃。
    model_config = ConfigDict(extra="forbid")

    item_code: Optional[str] = Field(None, description="招标文件工程量清单表格【第一列序号】中的原始编码（如'(一)'、'1'、'1.1'、'1.2'等，必须 100% 原样摘录；点号编码只有在表格同时明确展示成套组成关系时才作为层级线索）")
    item_name: str = Field(..., description="设备/软件/材料/元器件名称")
    specifications: Optional[str] = Field(None, description="规格型号或详细技术参数要求")
    quantity: Optional[float] = Field(None, description="项目总采购数量或工程量，纯数字。对于设备/材料表示物理采购数量，对于施工/服务项目表示原文工程量或服务次数。若为多级嵌套子项，必须严格按照穿透连乘公式计算：顶层数量 * 各层级单套定额！若原文仅给出计价单位而未写明具体数量，必须输出 null！绝对禁止脑补填 1！")
    unit: Optional[str] = Field(None, description="物理/计价单位（如：平方米、块、台、套、面、组、只、人月）")
    brand_requirements: Optional[str] = Field(None, description="品牌或产地要求（如：'进口原装'、'指定某品牌/某品牌或同等及以上品牌'、'国产自主可控'）")
    key_parameters: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件明确要求的核心技术指标/关键星号(*)参数"
    )
    parent_item: Optional[str] = Field(None, description="直接父级设备/总成名称。仅当原文通过‘每套包含/含有/配置’、视觉缩进、合并单元格或独立 BOM 结构明确展示组成关系时填写；普通工程量清单中的分组标题和独立计价行填 null")
    root_item: Optional[str] = Field(None, description="真实 BOM 父子关系中的顶层主要标的物名称；普通扁平工程量清单行填 null")
    tree_level: Optional[int] = Field(1, description="真实 BOM 层级深度；普通扁平工程量清单（包括仅有 2.6.1、2.6.2 编号的平级行）统一为 1；不能仅按点号数量推断")
    per_set_quantity: Optional[float] = Field(None, description="真实成套父项内部的单套定额；普通工程量清单或无法确认组成关系的行填 null")
    section_name: Optional[str] = Field(None, description="当前清单行明确所属的区域/分标段/分项工程/子系统名称；必须来自当前表格或其前置标题，原文未划分时为 null")
    section_evidence: Optional[str] = Field(None, description="支持 section_name 的原文短标题或表内分区文字，必须逐字摘录当前上下文；无法确认时为 null")

    @field_validator("section_name", mode="before")
    @classmethod
    def validate_section_name(cls, value: object) -> Optional[str]:
        """校验模型返回的所属分项字段，无法确认时统一置空。"""
        if value is None:
            return None
        if not isinstance(value, str):
            logger.warning(
                "[EngineeringService] section_name 类型无效，已置空：类型=%s",
                type(value).__name__,
            )
            return None

        normalized_value = normalize_engineering_section_name(value)
        if not is_valid_engineering_section_name(normalized_value):
            logger.warning(
                "[EngineeringService] section_name 未通过通用字段校验，已置空：值=%s",
                value,
            )
            return None
        return normalized_value

    @field_validator("section_evidence", mode="before")
    @classmethod
    def validate_section_evidence(cls, value: object) -> Optional[str]:
        """清理分区证据字段，避免把整段上下文写入结构化结果。"""
        if value is None:
            return None
        if not isinstance(value, str):
            logger.warning(
                "[EngineeringService] section_evidence 类型无效，已置空：类型=%s",
                type(value).__name__,
            )
            return None
        normalized_value = re.sub(r"\s+", " ", value).strip()
        if not normalized_value or len(normalized_value) > 160:
            logger.warning(
                "[EngineeringService] section_evidence 长度无效，已置空：长度=%d",
                len(normalized_value),
            )
            return None
        return normalized_value

class TechValidationRequirement(BaseModel):
    """技术验证、样品与演示要求（一票否决/高分项）"""
    # 严格限制结构化输出字段，便于及时发现模型输出协议漂移。
    model_config = ConfigDict(extra="forbid")

    sample_required: Optional[bool] = Field(False, description="开标现场是否需要提供物理样品/样机")
    sample_description: Optional[str] = Field(None, description="样品/样机送达与封样要求")
    poc_demo_required: Optional[bool] = Field(False, description="是否需要现场 POC 演示或软件系统功能答辩")
    test_report_requirements: Optional[list[str]] = Field(
        default_factory=list, 
        description="要求的第三方检测/测试报告明细（如：['须具备某种第三方认证机构出具的检测报告']）"
    )

class EngineeringSchema(BaseModel):
    # 顶层字段必须严格匹配 EngineeringSchema，禁止错误字段名被忽略后变成默认空数组。
    model_config = ConfigDict(extra="forbid")

    # --- 1. 主要标的物与设备清单 (生成《技术偏离表》与精细化 BOM) ---
    main_equipment_list: list[EquipmentItem] = Field(
        default_factory=list, 
        description="设备、材料以及有明确计价依据的施工/服务工程量清单明细"
    )

    # --- 2. 施工工况与技术实施难点 (检索工艺知识库) ---
    special_working_conditions: Optional[list[str]] = Field(
        default_factory=list, 
        description="特殊/高难度施工/实施工况（如：['高空/跨区域布线', '不停机业务迁移', '夜间施工']）"
    )
    site_environment_constraints: Optional[str] = Field(
        None, 
        description="现场环境与施工限制说明"
    )

    # --- 3. 规范、标准与技术依据 ---
    mandatory_standards: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件要求的强制性国家/行业/技术标准"
    )

    # --- 4. 技术验证、样品与检测报告 ---
    tech_validation: Optional[TechValidationRequirement] = Field(
        None, 
        description="样品送样、现场 POC 答辩演示及第三方权威检测报告要求"
    )

    # --- 5. 安全防护与文明施工要求 ---
    safety_and_env_requirements: Optional[list[str]] = Field(
        default_factory=list, 
        description="安全生产、文明施工及环保特别约束"
    )

    # --- 推导过程 ---
    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")


class EngineeringService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EngineeringMetadata)

    def _save_to_db(self, document_id: str, pydantic_obj: BaseModel) -> None:
        """防止一次异常的空提取覆盖数据库中已有的有效工程清单。"""
        equipment_list = getattr(pydantic_obj, "main_equipment_list", None)
        if equipment_list == [] and document_id:
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                existing_record = (
                    db.query(EngineeringMetadata)
                    .filter(EngineeringMetadata.document_id == document_id)
                    .first()
                )
                if existing_record and existing_record.main_equipment_list:
                    logger.warning(
                        "[EngineeringService] 本次提取结果为空，保留数据库已有工程清单：文档ID=%s，已有明细=%d",
                        document_id,
                        len(existing_record.main_equipment_list),
                    )
                    return
            finally:
                db.close()

        super()._save_to_db(document_id, pydantic_obj)

    @staticmethod
    def _repair_boq_hierarchy_from_source(
        items: list[EquipmentItem],
        source_context: str,
        item_table_indexes: Optional[dict[int, int]] = None,
    ) -> list[EquipmentItem]:
        """依据完整表格的结构边界补齐模型遗漏的分组父项。

        大模型负责语义抽取，但可能遗漏视觉上像分类标题的计价分组行。
        这里不识别任何具体项目名称，只使用原始表格的括号编码、列结构、
        明细编码和“下一个同级编码为边界”等通用证据恢复父子关系。
        """
        if not items or not source_context:
            return items

        source_tables = _source_rows_from_context(source_context)
        if not source_tables:
            logger.debug("[EngineeringService] 上下文未解析出 HTML 表格，跳过源表结构修复。")
            return items
        if item_table_indexes is None:
            assignments, _ = _assign_items_to_source_tables(items, source_tables)
            item_table_indexes = {
                id(items[item_index]): table_index
                for item_index, table_index in assignments.items()
            }

        def item_key(value: Optional[str]) -> str:
            """统一模型字段与原始单元格的空白及 HTML 实体差异。"""
            return _normalize_source_cell(value)

        def is_priced_section(row: _SourceTableRow) -> bool:
            """判断括号分组行是否同时拥有明确单位和数量。"""
            return bool(row.unit and row.quantity is not None)

        def find_item_index(
            source_row: _SourceTableRow,
            used_indexes: set[int],
            table_index: Optional[int] = None,
        ) -> Optional[int]:
            """按编码、名称、规格和单位为原始行寻找唯一的模型项。"""
            source_code = item_key(source_row.item_code)
            source_name = item_key(source_row.item_name)
            source_specification = item_key(source_row.specifications)
            source_unit = item_key(source_row.unit)
            candidates: list[tuple[int, int]] = []
            for index, item in enumerate(items):
                if index in used_indexes or item_key(item.item_name) != source_name:
                    continue
                if (
                    item_table_indexes is not None
                    and table_index is not None
                    and item_table_indexes.get(id(item)) != table_index
                ):
                    continue
                model_code = item_key(item.item_code)
                if model_code and source_code and model_code != source_code:
                    continue
                score = 20 if model_code == source_code and source_code else 0
                if source_specification and item_key(item.specifications) == source_specification:
                    score += 10
                if source_unit and item_key(item.unit) == source_unit:
                    score += 5
                candidates.append((score, index))
            if not candidates:
                return None
            # 同名同编码跨表重复时，规格/单位相同的项优先；仍相同则保持模型原顺序。
            return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]

        insertions: dict[int, list[EquipmentItem]] = {}
        used_indexes: set[int] = set()
        repaired_parent_count = 0
        repaired_child_count = 0
        cleared_boundary_count = 0

        for table_rows in source_tables:
            if not table_rows:
                continue
            # 使用原始表格编号与模型分块的表格归属保持一致。
            table_index = table_rows[0].table_index
            marker_positions = [
                index
                for index, row in enumerate(table_rows)
                if _is_section_marker_code(row.item_code)
            ]
            for marker_offset, marker_index in enumerate(marker_positions):
                section_row = table_rows[marker_index]
                section_end = (
                    marker_positions[marker_offset + 1]
                    if marker_offset + 1 < len(marker_positions)
                    else len(table_rows)
                )
                section_children = [
                    row
                    for row in table_rows[marker_index + 1 : section_end]
                    if _is_plain_child_code(row.item_code) and row.item_name.strip()
                ]
                if not section_children:
                    continue

                # 点号编码说明该范围可能是成套 BOM，交给原有递归层级逻辑处理，
                # 避免把真实的“1.1/1.2”子项误改成括号分组的直接子项。
                has_nested_children = any(
                    re.fullmatch(r"\d+(?:\.\d+)+", row.item_code.strip())
                    for row in table_rows[marker_index + 1 : section_end]
                )
                if has_nested_children:
                    continue

                matched_children: list[int] = []
                for child_row in section_children:
                    child_index = find_item_index(child_row, used_indexes, table_index)
                    if child_index is not None:
                        used_indexes.add(child_index)
                        matched_children.append(child_index)
                if not matched_children:
                    continue

                parent_index = find_item_index(section_row, used_indexes, table_index)
                if is_priced_section(section_row):
                    if parent_index is None:
                        first_child_index = min(matched_children)
                        first_child = items[first_child_index]
                        parent_item = EquipmentItem(
                            item_code=section_row.item_code,
                            item_name=section_row.item_name,
                            specifications=section_row.specifications,
                            quantity=section_row.quantity,
                            unit=section_row.unit,
                            section_name=first_child.section_name,
                        )
                        insertions.setdefault(first_child_index, []).append(parent_item)
                        if item_table_indexes is not None:
                            item_table_indexes[id(parent_item)] = table_index
                        parent_name = parent_item.item_name.strip()
                        repaired_parent_count += 1
                    else:
                        used_indexes.add(parent_index)
                        parent_name = items[parent_index].item_name.strip()

                    for child_index in matched_children:
                        child = items[child_index]
                        child.parent_item = parent_name
                        child.root_item = parent_name
                        child.tree_level = 2
                        child.per_set_quantity = None
                        repaired_child_count += 1
                else:
                    # 无计价父行只承担表格边界作用，不能被当作成本父项。
                    # 清理模型跨分组继承的父级，保证下一个分组从平级开始。
                    for child_index in matched_children:
                        child = items[child_index]
                        if (
                            child.parent_item
                            or child.root_item
                            or (child.tree_level or 1) != 1
                            or child.per_set_quantity is not None
                        ):
                            child.parent_item = None
                            child.root_item = None
                            child.tree_level = 1
                            child.per_set_quantity = None
                            cleared_boundary_count += 1

        if insertions:
            repaired_items: list[EquipmentItem] = []
            for index, item in enumerate(items):
                repaired_items.extend(insertions.get(index, []))
                repaired_items.append(item)
            items = repaired_items

        if repaired_parent_count or repaired_child_count or cleared_boundary_count:
            logger.info(
                "[EngineeringService] 按原始表格结构修复清单层级："
                f"补回计价分组父项={repaired_parent_count}，"
                f"绑定分组明细={repaired_child_count}，"
                f"清理边界串挂={cleared_boundary_count}"
            )
        return items

    @staticmethod
    def _normalize_boq_hierarchy(
        items: list[EquipmentItem],
        preserve_structural_nodes: bool = False,
        item_table_indexes: Optional[dict[int, int]] = None,
    ) -> list[EquipmentItem]:
        """根据表格中可验证的成套证据归一化 BOM 父子层级。

        仅有点号编号时仍按普通 BOQ 处理；当同一分支同时出现成套组成语义、
        单套定额或明确的根项时，才使用编号和父项行恢复真实的多级 BOM。
        生成展示树时可保留没有数量/单位的结构节点，但这类节点不参与成本计价。
        """
        if not items:
            return []

        # 当前提取链路已知每个模型项所属的原始表格时，必须逐表归一化。
        # 这样重复出现的 1、1.1、(一) 只在本表内参与父级查找，避免跨表串挂。
        scoped_table_indexes = {
            table_index
            for item in items
            if (table_index := item_table_indexes.get(id(item))) is not None
        } if item_table_indexes else set()
        if scoped_table_indexes:
            grouped_items: dict[int, list[EquipmentItem]] = {
                table_index: [] for table_index in sorted(scoped_table_indexes)
            }
            unscoped_items: list[EquipmentItem] = []
            for item in items:
                table_index = item_table_indexes.get(id(item)) if item_table_indexes else None
                if table_index is None:
                    unscoped_items.append(item)
                else:
                    grouped_items.setdefault(table_index, []).append(item)

            normalized_items: list[EquipmentItem] = []
            for table_index in sorted(grouped_items):
                normalized_items.extend(
                    EngineeringService._normalize_boq_hierarchy(
                        grouped_items[table_index],
                        preserve_structural_nodes=preserve_structural_nodes,
                    )
                )
            if unscoped_items:
                # 未能与原始表格对齐的异常模型项不参与跨表推断，单独按普通清单处理。
                normalized_items.extend(
                    EngineeringService._normalize_boq_hierarchy(
                        unscoped_items,
                        preserve_structural_nodes=preserve_structural_nodes,
                    )
                )
            logger.info(
                "[EngineeringService] 已按原始表格边界执行 BOQ 层级归一化：表格数=%d，未对齐项=%d",
                len(grouped_items),
                len(unscoped_items),
            )
            return normalized_items

        def clean_code(item: EquipmentItem) -> str:
            """读取清单原始编码并去除 OCR 产生的首尾空白。"""
            return str(item.item_code or "").strip()

        def is_priced(item: EquipmentItem) -> bool:
            """判断行是否拥有数量或单位等计量信息。"""
            return item.quantity is not None or bool(str(item.unit or "").strip())

        def is_root_code(code: str) -> bool:
            """识别表格中常见的中文括号根项编码。"""
            return bool(re.fullmatch(r"[（(][一二三四五六七八九十百千万]+[）)]", code))

        def is_composition_marker(item: EquipmentItem) -> bool:
            """识别原文明确表达成套组成关系的表格文本。"""
            text = f"{item.item_name} {item.specifications or ''}"
            return bool(
                re.search(
                    r"每(?:套|台|面|组|柜|箱)包含|内含|含有|组成|配置|配套|内部包括|每套含",
                    text,
                )
            )

        def parent_code(code: str) -> Optional[str]:
            """获取点号编码的直接上级编码。"""
            if not re.fullmatch(r"\d+(?:\.\d+)+", code):
                return None
            return code.rsplit(".", 1)[0]

        # 同一份招标文件中不同表格可能重复使用 1、1.1 等编码，不能使用全局单值索引。
        code_index: dict[str, list[int]] = {}
        for index, item in enumerate(items):
            code = clean_code(item)
            if code:
                code_index.setdefault(code, []).append(index)

        # 只有“有计量根项 + 表内递进编码 + 成套组成证据”同时成立时，才启用 BOM 模式。
        priced_root_indexes = [
            index
            for index, item in enumerate(items)
            if is_root_code(clean_code(item)) and is_priced(item)
        ]
        # 无数量的括号标题（例如“其它”或“土建配套部分”）也要作为上一棵树的边界，
        # 否则后续独立表格从 1 重新编号时，可能被误挂到上一根 BOM 下。
        root_boundary_indexes = [
            index for index, item in enumerate(items) if is_root_code(clean_code(item))
        ]
        branch_ranges: list[tuple[int, int]] = []
        for root_index in priced_root_indexes:
            next_boundaries = [boundary for boundary in root_boundary_indexes if boundary > root_index]
            branch_end = next_boundaries[0] if next_boundaries else len(items)
            branch_ranges.append((root_index, branch_end))

        def find_branch(index: int) -> Optional[tuple[int, int]]:
            """返回当前行所属的显式根项分支。"""
            for start, end in branch_ranges:
                if start <= index < end:
                    return start, end
            return None

        def find_candidate_parent(index: int, expected_code: str, branch: Optional[tuple[int, int]]) -> Optional[int]:
            """在当前分支内寻找直接父行，优先选择当前行之前最近的一行。"""
            candidates = code_index.get(expected_code, [])
            if branch:
                candidates = [candidate for candidate in candidates if branch[0] <= candidate < branch[1]]
            prior_candidates = [candidate for candidate in candidates if candidate < index]
            if prior_candidates:
                return prior_candidates[-1]
            return candidates[0] if candidates else None

        def has_priced_section_children(branch: tuple[int, int]) -> bool:
            """识别“项”类计价分组下数量待设计、但有单位的明细行。"""
            start, end = branch
            root_item = items[start]
            if str(root_item.unit or "").strip() not in {"项", "项目"}:
                return False
            return any(
                re.fullmatch(r"\d+", clean_code(child))
                and child.quantity is None
                and bool(str(child.unit or "").strip())
                for child in items[start + 1 : end]
            )

        def has_explicit_section_parent(branch: tuple[int, int]) -> bool:
            """保留已由原始表格结构确认的分组父子关系。"""
            start, end = branch
            root_name = items[start].item_name.strip()
            return any(
                re.fullmatch(r"\d+", clean_code(child))
                and child.parent_item == root_name
                and child.root_item == root_name
                for child in items[start + 1 : end]
            )

        branch_has_bom_evidence: dict[tuple[int, int], bool] = {}
        for branch in branch_ranges:
            start, end = branch
            branch_items = items[start:end]
            has_nested_code = any(
                parent_code(clean_code(item))
                and find_candidate_parent(index, parent_code(clean_code(item)) or "", branch) is not None
                for index, item in enumerate(items[start:end], start=start)
            )
            has_composition_evidence = any(
                is_composition_marker(item) or item.per_set_quantity is not None
                for item in branch_items
            )
            # PDF 中“导体和导线”“铁附件”等分组自身按“项”计价，明细数量留空但单位明确，
            # 这同样是可验证的父子分组证据，不能按普通平级 BOQ 清理。
            has_section_group_evidence = (
                has_priced_section_children(branch)
                or has_explicit_section_parent(branch)
            )
            branch_has_bom_evidence[branch] = (
                has_nested_code and has_composition_evidence
            ) or has_section_group_evidence

        normalized_items: list[EquipmentItem] = []
        dropped_group_count = 0
        repaired_hierarchy_count = 0

        for index, item in enumerate(items):
            item_code = clean_code(item)
            branch = find_branch(index)
            has_bom_evidence = bool(branch and branch_has_bom_evidence.get(branch))
            expected_parent_code = parent_code(item_code)
            expected_parent_index = (
                find_candidate_parent(index, expected_parent_code, branch)
                if expected_parent_code
                else None
            )

            # 显式根项是树的 Level 1；根项名称同时作为整棵分支的 root_item。
            if is_root_code(item_code) and is_priced(item):
                item.parent_item = None
                item.root_item = item.item_name.strip()
                item.tree_level = 1
                item.per_set_quantity = None

            # 无计量的行只有在真实 BOM 分支中被递进编码子项引用时才保留为结构父级；
            # 普通 BOQ 的分类标题继续移除，防止“接地”等标题污染成本清单。
            is_referenced_parent = any(
                parent_code(clean_code(child)) == item_code
                for child in items
                if clean_code(child) != item_code
            )
            if not is_priced(item) and not (has_bom_evidence and is_referenced_parent):
                if preserve_structural_nodes:
                    # 目标 BOM 树需要保留原文中的分组标题和无计量说明节点，
                    # 但它们没有可计量依据，不能被当成价格匹配项。
                    item.tree_level = max(int(item.tree_level or 1), 1)
                    item.per_set_quantity = None
                    normalized_items.append(item)
                    continue
                dropped_group_count += 1
                continue

            # 显式根项下的 1、2 等成套分项，以及 1.1、2.1 等递进子项，
            # 只有在表内存在成套证据时才按 PDF 的父子结构绑定。
            if has_bom_evidence and branch and not (is_root_code(item_code) and is_priced(item)):
                root_item = items[branch[0]]
                if expected_parent_index is not None:
                    expected_parent = items[expected_parent_index]
                    item.parent_item = expected_parent.item_name.strip()
                    item.root_item = root_item.item_name.strip()
                    item.tree_level = (expected_parent.tree_level or 1) + 1
                    repaired_hierarchy_count += 1
                elif re.fullmatch(r"\d+", item_code):
                    # 根项下的一级数字行（如“1 环网柜”“2 10kV 变压器”）是根项的直接子级。
                    item.parent_item = root_item.item_name.strip()
                    item.root_item = root_item.item_name.strip()
                    item.tree_level = 2
                    repaired_hierarchy_count += 1
            elif expected_parent_index is not None:
                # 非 BOM 分支中，若模型将无计量分类标题当成父项，恢复为平级 BOQ。
                expected_parent = items[expected_parent_index]
                if not is_priced(expected_parent):
                    item.parent_item = None
                    item.root_item = None
                    item.tree_level = 1
                    item.per_set_quantity = None
                    repaired_hierarchy_count += 1
            elif not has_bom_evidence and re.fullmatch(r"\d+", item_code):
                # 新表格重新从 1 编号时，清理模型从上一张成套表格错误继承的父级。
                if item.parent_item or item.root_item or (item.tree_level or 1) != 1 or item.per_set_quantity is not None:
                    item.parent_item = None
                    item.root_item = None
                    item.tree_level = 1
                    item.per_set_quantity = None
                    repaired_hierarchy_count += 1

            normalized_items.append(item)

        if dropped_group_count or repaired_hierarchy_count:
            logger.info(
                "[EngineeringService] BOQ 层级归一化完成："
                f"移除非计价分组行={dropped_group_count}，修复伪父子关系={repaired_hierarchy_count}"
            )
        return normalized_items

    def extract_metadata(
        self,
        context: str,
        document_id: str,
        tenant_id: Optional[str] = None,
    ) -> EngineeringSchema:
        from app.utils.table_utils import extract_equipment_tables_and_context
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import re
        from app.core.context import current_tenant_id

        # 在线程池中显式传递租户，避免 ContextVar 未继承时回退到 global 配置。
        effective_tenant_id = tenant_id or current_tenant_id.get()

        # 仅按表格语法提取上下文，保留检索结果中的完整表格，不在送模前按业务规则过滤清单行。
        clean_context = extract_equipment_tables_and_context(context)

        system_prompt = r"""
你是资深的【项目总工与工程造价清单专家】。你的任务是从传入的技术图纸说明、工程量清单、《项目需求》、《技术规格书》和《货物需求一览表》中，提取出**设备、材料以及有明确计价依据的施工/服务 BOQ 行项目**。

【零容忍数字幻觉（最高指令）】
系统对参数极为严格，你提取的任何设备数量、技术指标必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。
- **关于数量 `quantity`**：若标书原文中仅给出了计价单位（如“平方米”、“米”），但未标注具体物理采购数量，`quantity` 必须输出为 null，绝对禁止脑补填 1！

【提取指南】
1. **完整工程量清单行项目提取（最高优先级）**：
   - 当前任务目标是逐行完整提取 BOM/BOQ 表格中的设备、材料、安装、施工、运输、调试、检测和其他服务项目，不仅提取核心设备或已经明确数量的项目。只要原文行具有独立的项目名称、组成部件名称、规格描述、计量单位、数量/工程量或明确的成套组成语义，就必须输出一个 `EquipmentItem`。
   - **逐行核对要求（必须执行）**：从表头下一行开始，按照原文表格顺序逐行检查，不能因为前面已经识别出主要设备、当前行缺数量、当前行没有独立编码或当前行位于 `rowspan`/`colspan` 跨行结构中就跳过。模型返回结果必须覆盖当前表格中所有可识别的独立清单行；只有空行、表头、纯分组标题、纯备注和不代表独立项目的连续说明可以不输出。
   - **数量与计价字段规则**：数量/工程量明确写出时原样填入；原文未写出时 `quantity` 必须为 null，不能脑补。缺少数量或单位不等于该行无效，若该行是独立设备、材料、服务或明确的 BOM 组成项，仍必须保留，其缺失字段分别填 null。
   - 对于表格中的施工/服务行，即使单位是“项”“批”“次”“日”“人月”，或名称看起来像施工工序，也必须保留；数量没有填写时只将 `quantity` 设为 null，不得因此跳过该行。
   - 表格中的纯分组标题/分类行（不代表设备、材料、服务或 BOM 结构节点）不是清单项，不得输出为 `EquipmentItem`。但是，原文明确展示内部组成关系的成套设备父项、子系统节点和组成部件必须保留，即使其中部分行没有独立数量或单位。
   - **明确排除非项目叙述**：安全生产制度、文明施工要求、岗位职责、人员分工、作业票要求、风险提示、违章分类、施工方法、管理流程、培训要求、验收说明、处罚条款、评标规则、合规承诺和一般技术规范，均不得作为 BOM/BOQ 项目；只有当原文明确把它们列为独立工程量、报价或服务项目时才保留。
   - 只有表头、空白行、纯注释、纯说明、合计/小计行（且不代表实际工作内容）可以不作为清单项输出。禁止把“在某区域内使用某种作业票”“工作负责人不在现场”“满足某安全要求”等句子提取为项目。
   - 设备、材料、施工和服务项目统一使用同一套 `EquipmentItem` 结构：项目名称或工作内容填入 `item_name`，原文技术要求/施工内容/服务范围填入 `specifications`，原文数量填入 `quantity`，原文单位填入 `unit`。数量必须是纯数字；原文没有数量时必须为 `null`。
   - **完整保留表格上下文**：必须结合当前表格的全部列、跨行表头、合并单元格内容、表格前后的章节标题和技术说明判断每一行含义；不得只依据“设备名称”列筛选，也不得因为某行名称与设备无关而跳过。
   - **【主要标的物聚焦与宏观大类归口原则（最高指令）】**：
     - 清单提取应紧紧围绕招标文件中的《货物需求一览表》、《工程量清单》、《采购清单》、《报价清单》和核心设备材料表；其他章节只作为技术上下文，不能仅凭其中的要求、制度或说明生成 BOM 项目。
       - **关于 `section_name`（当前清单表的外层所属分区）**：
       - `section_name` 只表示当前清单表所属的外层区域、标段、部分或分项名称；同一张表中的所有清单行原则上必须保持一致。
       - 表格标题中的“项目需求清单/报价清单”等包装文字不是展示名称；若其括号中包含明确的外层部分名称，可以提取括号内语义名称。
       - 每条 `EquipmentItem` 都必须返回 `section_name` 和 `section_evidence`；证据必须逐字摘录当前表格前的外层标题，且必须包含 `section_name`。禁止把表内“光伏发电设备”“电缆及附件”等内部分类写入 `section_name`。
       - 表内分组、子系统、设备总成及其递进明细属于 BOM 层级信息，必须通过 `parent_item`、`root_item`、`tree_level` 表达，不属于 `section_name`。只有当前表格没有外层标题、且原文另有明确独立分区时，才可使用该分区；否则返回 null。
       - 大模型可以先筛选清单行并返回候选分区供后端核验，但最终 `section_name` 必须归一到当前表格的外层分区，不得使用更具体的表内分组覆盖外层分区。
   - **【真实 BOM 层级与普通 BOQ 编号严格区分（最高优先级）】**：
     - 不能仅因点号编号、行号连续、名称相似或前一行刚好出现就建立父子关系。普通工程量清单中同一分组下的连续编号行应保持平级，例如抽象形式 `A.1`、`A.2`、`A.3` 的多个计价行统一输出 `parent_item=null`、`root_item=null`、`tree_level=1`、`per_set_quantity=null`。
     - 若表格出现“根项数量 + 每套包含/含有/配置”等成套语义，并且通过视觉缩进、合并单元格、独立物料清单结构或递进编码展示组成关系，则这些结构证据共同确认真实 BOM。此时必须保留根项、成套分项和所有递进子项，不能把子项合并进父项规格。
     - 真实 BOM 的抽象结构可能是：`(二) 成套系统（数量 Q）` → `1 总成（每套包含）` → `1.1 子件`、`1.2 子件`；或 `2 功能单元` → `2.1 元件`。其中 `1`、`2` 是根项的直接子级，`1.1`、`1.2` 是 `1` 的直接子级，`2.1` 是 `2` 的直接子级，不能把所有点号行都挂到根项，也不能把兄弟项串成链。
     - 无数量/单位但被真实 BOM 子项引用的结构父级（例如“功能单元”分组行）必须保留为父节点，以便完整还原 PDF 树；它不应被当成可独立计价项，也不能成为普通 BOQ 的父项。
     - 为了完整还原 BOM 树，清单表中的结构性分组标题、子系统标题和无计量说明节点也要保留为树节点；这类节点的 `quantity`、`unit` 和 `per_set_quantity` 必须为 null，成本匹配时必须跳过。
     - 表格中带有括号分组编码、且同行明确有单位和数量的分组行，如果其后紧邻同一表格的普通整数编码明细，必须保留该分组行并将这些明细绑定为直接子项；遇到下一个同级括号编码时立即结束当前分组。即使分组名称没有“包含/组成”等词，也不能省略这个计价父项。
     - 只有在上述结构证据成立时，才填写 `parent_item`、`root_item`、`tree_level` 和 `per_set_quantity`；仅有编号层级时按扁平清单处理。
   - **【任意深度多级嵌套 BOM 设备树（Multi-Level BOM 任意 N 级递归穿透提取，最高指令）】**：
     - 当工程量清单表格中出现包含任意多层嵌套缩进、层级递进编号（如顶层复合系统 $\\rightarrow$ 二级总成 $\\rightarrow$ 三级组件 $\\rightarrow$ 四级模块 $\\rightarrow$ 五级元器件等任意 $N$ 级树状结构）时，必须严格按以下【通用递归归纳法则】逐级完整拆解：
     
     - **【零文本合并红线（通用递归约束）】**：
       - **凡是在表格中带有独立层级编码（如点号递进序号、缩进编号）、独立计量单位或独立单台定额的任何部件/元器件，无论嵌套层级有多深（Level 1 至 Level N），必须 100% 逐行拆解输出为独立的 `EquipmentItem` 记录！**
       - **绝对禁止将第 $L+1$ 级或更深层的子部件合并压缩成一段概括性文字塞进第 $L$ 级父节点的 `specifications` 描述中！**

     - **【通用 N 级递归字段赋值与连乘规则（数学归纳法）】**：
       1. **层级深度判定 (`tree_level`)**：
          - 设最顶层主要标的物为 Level 1（`tree_level = 1`）；
          - 依据真实的父项组成语义、视觉缩进、合并单元格或独立 BOM 结构确定当前节点层级；序号点号数量只能作为辅助线索，不能单独决定 `tree_level`。
       2. **直接父级绑定 (`parent_item`)**：
          - 若 $L = 1$（顶层根节点），`parent_item` 必须为 null；
          - 若 $L \\ge 2$（任意子项/孙项节点），`parent_item` **必须且仅能严格指向其直接所属的上一级（Level $L-1$）父节点的完整名称**。
       3. **顶层根设备绑定 (`root_item`)**：
          - 整个分支树下的所有层级节点（Level 1 至 Level $N$），其 `root_item` **必须全部统一填入该分支最顶层 Level 1 根标的物的名称**。
       4. **单台配置定额 (`per_set_quantity`)**：
          - 若 $L = 1$，`per_set_quantity` 填 null；
          - 若 $L \\ge 2$，`per_set_quantity` **必须准确填入在单台直接父级（Level $L-1$ 设备）中的物理配置数量**（纯数字 $q_L$）。
       5. **项目总需求量/工程量递归穿透连乘换算 (`quantity`)**：
          - 若 $L = 1$，`quantity` 填该顶层标的物、施工项目或服务项目在整个项目中的原文总数量/工程量（纯数字 $Q_1$）；
          - 若 $L \ge 2$，当前子项在整个项目中的总需求量或工程量 **必须通过从顶层至当前层级的全链路单套定额递归连乘公式准确换算**：
            $$\text{quantity} = Q_1 \times q_2 \times q_3 \times \dots \times q_L$$
            （即：顶层总套数 $Q_1$ 乘以该分支路径上各级单套定额的乘积）。
       6. **规格与技术参数 (`specifications`)**：
          - 每一个节点（无论处于哪一层级）的 `specifications` **仅摘录其自身的物理型号、尺寸、电气指标与材质参数**，严禁掺杂下级子部件清单文字。
     - 若清单为普通扁平表格，或无法确认真实组成关系，则所有条目的 `parent_item`、`root_item` 和 `per_set_quantity` 统一输出为 null，`tree_level` 统一填 1，`quantity` 为原文物理采购数量/工程量。
   - **【明细表格精确数值优先原则】**：当清单表格中列出的具体型号或精确数量与前言概述文字存在出入时，**一律以明细表格中的精确数值为准**。
   - **关于 `specifications`（规格参数要求）**：**必须 100% 原汁原味完整摘录标书原文中的详细技术参数描述**（包含所有型号参数、材质、尺寸、物理/电气指标等）。
   - **拒绝“详见XXX”废话（最高指令）**：若清单表格中写有“详见技术规格”、“详见项目需求”、“详见第五章”等引用说明，**绝不能直接把“详见XXX”当作规格参数！你必须从后文《技术规格书/项目需求》章节中找到该设备真实的详细规格与技术要求完整摘录填入！**
   - **关于 `key_parameters`**：请从原文中提炼具体的**技术参数指标**（如精确的厚度、材质要求、功率、吞吐量等具有明确物理/化学测量依据的约束），**绝对禁止**提取诸如“使用寿命长”、“防腐防水防火”、“风格协调”之类的假大空废话或主观描述！
   - **极度注意（防止断章取义）**：提取参数时，**必须将该指标生效的【前置条件/测试环境】一并提取**！例如，绝不能只提取“某指标≥某数值”，必须完整提取“在XXX温度、XXX压力、XXX测试条件约束下，该指标≥某数值”。必须将所有带 '*' 号的参数以及带有完整条件的明确技术门槛原汁原味地填入该数组。
2. **特殊工况**：排查“现场踏勘”、“注意事项”。提取特殊的高成本/高风险工况（如“高空作业”、“带电施工”、“特殊环境防护”等）。
3. **技术标准**：提取明确规定的“国家标准”、“行业标准”。这决定了我们的编制依据。
4. **技术验证与样品（死亡雷区）**：重点去《评标办法》或《投标人须知》中寻找“样品”、“检测报告”、“CMA”、“CNAS”、“现场演示(POC)”的字眼，这关乎是否废标。
5. **安全与环保**：提取现场必须遵守的安全红线。

请在 `reasoning` 字段中简要说明你是如何找出这些痛点和核心物资的。
如果上下文中没有任何相关的配置或要求信息，请严格将其输出为 null。绝对不可根据常识盲目瞎编。
"""
        # 识别正文中的所有表格
        html_tables = list(re.finditer(r'<table[\s\S]*?</table>', clean_context, re.IGNORECASE))
        md_tables = list(re.finditer(r'(?:(?:^|\n)\|[^\n]+\|\n(?:\|[-:\s|]+\|\n)(?:\|[^\n]+\|\n?)+)', clean_context, re.MULTILINE))
        all_tables = sorted(html_tables + md_tables, key=lambda x: x.start())
        table_section_hints = build_engineering_table_section_hints(clean_context, all_tables)
        table_section_hint_text = "\n".join(table_section_hints) or "- 未从表格前置标题确认到分区，请仅依据表内明确分区文字判断"
        context_limit = _get_engineering_context_limit()
        if len(all_tables) > 1:
            # 多表文件无论是否能识别出外层标题，都必须逐表提交，保证模型返回的
            # section_name 和后续层级修复始终带有表格边界。
            chunks, chunk_sections, chunk_table_indexes = _build_table_scoped_engineering_chunks(
                clean_context,
                all_tables,
                context_limit,
            )
        else:
            # 单表仍沿用原有拆分策略，表格内部的长表只按完整行拆分。
            chunks, chunk_sections = _build_semantic_engineering_chunks(
                clean_context,
                all_tables,
                context_limit,
            )
            # 单表超长拆分后仍属于同一张原始表，保留表格编号才能执行逐行对账。
            chunk_table_indexes = [0 if all_tables else None] * len(chunks)
        if not chunks:
            chunks = [clean_context]
            chunk_sections = [None]
            chunk_table_indexes = [None]

        logger.info(
            f"🚀 [EngineeringService] 发现 {len(all_tables)} 个原文表格块，"
            f"组装为 {len(chunks)} 个语义上下文分块后交由模型判断清单范围。"
        )

        def process_chunk(
            idx: int,
            chunk_text: str,
            section_title: Optional[str],
            table_index: Optional[int],
        ) -> tuple[int, Optional[EngineeringSchema]]:
            chunk_hint_text = (
                table_section_hints[table_index]
                if table_index is not None and table_index < len(table_section_hints)
                else table_section_hint_text
            )
            section_hint = f"""
【所属分项定位证据】
以下索引由当前上下文中每张表格前的原文标题生成，仅用于帮助模型把表格与最近分区对应起来，不得把候选值当作无证据结论：
{chunk_hint_text}
当前分块候选分区：{section_title or '未单独确认'}
请由模型结合对应表格、表内分区文字及其前置标题，逐条决定 `EquipmentItem.section_name`，并逐字返回对应的 `section_evidence`；原文不能确认时两个字段都必须返回 null。
"""
            prompt = f"""
{system_prompt}

【任务约束】
1. 你的任务是根据下面提供的【当前工程清单上下文与技术要求】进行信息抽取。当前分块只包含一张原文清单表及其前置标题，后端没有依据固定项目名称、章节名称或表头关键词预先筛掉表格；请你先判断表格是否属于 BOM/BOQ，再完整逐行提取其中所有可识别的清单项目。{section_hint}
   - 必须同时阅读表格的所有列及跨行、跨列单元格。遇到跨行结构时，只把重复出现的父项单元格视为同一个父项，把后续独立的组成内容逐项识别为子项或该父项的连续规格说明；不能因父项名称被 HTML `rowspan` 重复展示而生成重复父项，也不能因子项缺少独立编码而遗漏。
   - 后端不会根据原始表格另行补造清单项；模型返回的 `main_equipment_list` 必须是当前表格完整提取结果。父子关系、根项、层级和单套定额必须依据当前表格原文证据直接填写，无法确认时填 null 或保持默认平级值。
2. 宁缺毋滥原则：如果当前分块中完全没有提及某个字段的相关信息（找不到），请将该字段值置为 null。绝不允许编造任何信息。
3. **所属分项由模型筛选并提供证据**：`section_name` 只记录当前清单表的外层区域、标段、部分或分项名称。同一张表内的所有清单行原则上使用同一个外层 `section_name`；表内的“光伏发电设备”“电缆及附件”等内部分类必须通过 `parent_item`、`root_item`、`tree_level` 表达，不得写入 `section_name`。只有当前清单表没有外层标题、且原文存在明确独立分区时，才允许使用该分区。填写时必须同时返回逐字摘录的 `section_evidence`，证据必须来自当前上下文且包含 `section_name`；不得把合同章节、整句说明、表头包装文字、设备名称、编码或模型自拟名称写入该字段；无法确认时 `section_name` 与 `section_evidence` 都必须为 null。
4. 明确豁免原则：如果上下文中明确写明“无需提供”、“不作要求”，请针对该字符串字段返回 "明确无要求"；如果写明“待定”、“另行通知”，请返回 "待定"。千万不要返回 null。

<当前工程清单上下文与技术要求 (第 {idx + 1}/{len(chunks)} 上下文分块)>
{chunk_text}
</当前工程清单上下文与技术要求>
"""
            # 打印本次请求实际携带的文档上下文，便于核对表格边界和分区提示是否正确。
            logger.info(
                "[EngineeringService] 大模型输入文档上下文（分块 %d/%d）：\n%s%s",
                idx + 1,
                len(chunks),
                section_hint,
                chunk_text,
            )
            try:
                sub_res = llm_service.generate_structured_output(
                    prompt=prompt,
                    schema_cls=EngineeringSchema,
                    temperature=0.1,
                    tenant_id=effective_tenant_id,
                )
            except Exception as e:
                # 保留完整堆栈，避免并发分块失败后只剩下一个无法定位的空结果。
                logger.exception(f"分块 {idx + 1} 提取失败: {e}")
                return idx, None

            item_count = len(sub_res.main_equipment_list or [])
            item_names = [item.item_name for item in sub_res.main_equipment_list[:5]]
            logger.info(
                f"[EngineeringService] 分块 {idx + 1} 结构化结果: "
                f"设备明细={item_count}，所属分项={section_title or '未识别'}，"
                f"示例={item_names}，输入字符数={len(chunk_text)}"
            )
            # 记录模型未经过后端层级修复前的完整返回，便于确认遗漏发生在模型还是后处理阶段。
            logger.info(
                "[EngineeringService] 大模型返回完整结构化结果（分块 %d/%d）：\n%s",
                idx + 1,
                len(chunks),
                _schema_to_log_json(sub_res),
            )
            if not item_count:
                # 空结果仍允许参与其它字段汇总，但最终会在落库前统一拦截。
                logger.warning(
                    f"[EngineeringService] 分块 {idx + 1} 未提取到设备明细，"
                    "请检查该分块是否只包含表头、表格行是否被 RAG 截断或模型字段是否错配。"
                )
            return idx, sub_res

        chunk_results = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(5, len(chunks))) as executor:
            futures = [
                executor.submit(
                    process_chunk,
                    i,
                    chunk,
                    chunk_sections[i],
                    chunk_table_indexes[i],
                )
                for i, chunk in enumerate(chunks)
            ]
            for future in as_completed(futures):
                c_idx, c_schema = future.result()
                chunk_results[c_idx] = c_schema

        # 汇总合并各分块提取的设备清单与各项要求
        merged_equipment_list = []
        special_conditions = []
        mandatory_standards = []
        tech_validation = None
        safety_requirements = []
        reasoning_list = []

        for c_idx, schema_item in enumerate(chunk_results):
            if not schema_item:
                continue
            c_section = chunk_sections[c_idx]
            c_table_index = chunk_table_indexes[c_idx]
            chunk_item_names = {
                item.item_name
                for item in schema_item.main_equipment_list
                if item.item_name
            }
            if schema_item.main_equipment_list:
                for eq in schema_item.main_equipment_list:
                    # 模型先筛选清单行并返回候选分区；若当前表格已有明确外层标题，
                    # 最终字段统一归一到该外层标题，避免把表内分类误当 section_name。
                    model_section = normalize_engineering_section_name(eq.section_name)
                    if c_section and is_valid_engineering_section_name(c_section):
                        if model_section and model_section != c_section:
                            logger.info(
                                "[EngineeringService] 模型返回表内分组，已归一为表格外层分区："
                                f"分块={c_idx + 1}，模型值={model_section}，外层分区={c_section}"
                            )
                        eq.section_name = c_section
                        eq.section_evidence = c_section
                    elif model_section and (
                        is_valid_engineering_section_name(model_section)
                        and validate_engineering_section_evidence(
                            eq,
                            chunks[c_idx],
                            known_item_names=chunk_item_names,
                        )
                    ):
                        # 当前表格没有可确认的外层标题时，才保留模型自身核验通过的候选。
                        eq.section_name = model_section
                    else:
                        logger.warning(
                            "[EngineeringService] 当前表格无法确认有效外层分区，section_name 已置空："
                            f"分块={c_idx + 1}，模型值={model_section or '无'}，证据={eq.section_evidence or '无'}"
                        )
                        eq.section_name = None
                        eq.section_evidence = None
                merged_equipment_list.extend(schema_item.main_equipment_list)
            if schema_item.special_working_conditions:
                for c in schema_item.special_working_conditions:
                    if c not in special_conditions:
                        special_conditions.append(c)
            if schema_item.mandatory_standards:
                for s in schema_item.mandatory_standards:
                    if s not in mandatory_standards:
                        mandatory_standards.append(s)
            if schema_item.tech_validation and not tech_validation:
                tech_validation = schema_item.tech_validation
            if schema_item.safety_and_env_requirements:
                for sf in schema_item.safety_and_env_requirements:
                    if sf not in safety_requirements:
                        safety_requirements.append(sf)
            if schema_item.reasoning:
                reasoning_list.append(schema_item.reasoning)

        # 主流程只使用模型返回的清单，后端不再从原始表格补造项目或重建父子关系。
        # Pydantic 已完成类型、必填项和额外字段校验；分区字段继续在上方执行原文证据校验。
        logger.info(
            "[EngineeringService] 已完成模型清单汇总：设备明细=%d；未执行源表补行或后端层级推断。",
            len(merged_equipment_list),
        )

        failed_chunk_numbers = [idx + 1 for idx, item in enumerate(chunk_results) if item is None]
        empty_chunk_numbers = [
            idx + 1
            for idx, item in enumerate(chunk_results)
            if item is not None and not item.main_equipment_list
        ]
        if failed_chunk_numbers:
            logger.error(
                f"[EngineeringService] 分块提取失败清单: {failed_chunk_numbers}，"
                f"成功返回空设备清单的分块: {empty_chunk_numbers}"
            )

        # 所有分块均已完成后仍未得到设备项，按无可提取工程清单正常降级，不进行额外循环重试。
        if all_tables and not merged_equipment_list:
            diagnostic = (
                "检测到工程清单候选表格，但所有分块均未产生设备明细；"
                f"失败分块={failed_chunk_numbers or '无'}，空结果分块={empty_chunk_numbers or '无'}。"
            )
            logger.warning(
                f"[EngineeringService] {diagnostic} "
                "已完成全部分块处理，按无可提取工程清单继续保存其它工程元数据。"
            )

        final_schema = EngineeringSchema(
            main_equipment_list=merged_equipment_list,
            special_working_conditions=special_conditions,
            mandatory_standards=mandatory_standards,
            tech_validation=tech_validation,
            safety_and_env_requirements=safety_requirements,
            reasoning="; ".join(reasoning_list)
        )

        # 记录最终将要落库的完整结果，用于与模型原始返回和目标 BOM 树逐项对照。
        logger.info(
            "[EngineeringService] 工程清单最终归一化结果（文档ID=%s，设备明细=%d）：\n%s",
            document_id,
            len(merged_equipment_list),
            _schema_to_log_json(final_schema),
        )

        # 自动落盘数据库
        if self.db_model_cls and document_id:
            try:
                self._save_to_db(document_id, final_schema)
            except Exception as db_err:
                logger.warning(f"⚠️ 结构化数据提取成功，但落盘数据库失败 (文档ID: {document_id}): {db_err}")

        logger.info(f"✅ [EngineeringService] 语义上下文提取完成，成功汇总 {len(merged_equipment_list)} 项设备明细！")
        return final_schema

engineering_service = EngineeringService()
