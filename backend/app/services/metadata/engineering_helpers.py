from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from .engineering_models import EquipmentItem

from app.utils.text_normalizer import normalize_markup_text

logger = logging.getLogger(__name__)

# 分组模式由原始表格结构决定，不承载具体项目业务值。
GroupingMode = Literal["external", "internal", "none"]

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


@dataclass(frozen=True)
class _SourceStructuralCandidate:
    """源表中可恢复的无计量结构父项及其直接关联行。"""

    table_index: int
    row: _SourceTableRow
    child_rows: tuple[_SourceTableRow, ...]
    candidate_type: Literal["section", "hierarchy", "rowspan"]


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
    """归一化原始表格单元格，便于跨 OCR 与标记格式差异进行匹配。"""
    if not value:
        return ""
    # 原始表格可能保留 Markdown/LaTeX，而模型结果已在保存前完成标记清洗；
    # 对齐键必须使用同一套通用文本归一化，否则续表行无法继承前序分组。
    normalized_value = normalize_markup_text(unescape(value))
    return re.sub(r"\s+", "", str(normalized_value)).strip()


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
    """识别表格中独立的分组编码，兼容括号编码和中文大序号。"""
    normalized_value = re.sub(r"\s+", "", value or "").strip()
    return bool(
        re.fullmatch(r"[（(](?:[一二三四五六七八九十百千万]+|\d+)[）)]", normalized_value)
        or re.fullmatch(r"[一二三四五六七八九十百千万]+[、.．]?", normalized_value)
    )


def _is_bare_chinese_section_marker(value: str) -> bool:
    """识别不带括号的中文大序号，作为表内 BOQ 分类线索。"""
    normalized_value = re.sub(r"\s+", "", value or "").strip()
    return bool(
        re.fullmatch(r"[一二三四五六七八九十百千万]+[、.．]?", normalized_value)
    )


def _is_plain_child_code(value: str) -> bool:
    """识别分组下的普通整数明细编码。"""
    return bool(re.fullmatch(r"\d+", value.strip()))


def _is_dotted_hierarchy_code(value: str) -> bool:
    """识别工程量清单中用于表达递进目录的点号编码。"""
    return bool(re.fullmatch(r"\d+(?:\.\d+)+", (value or "").strip()))


def _hierarchy_code_depth(value: str) -> int:
    """将中文分组、括号分组和点号编码转换为可比较的目录深度。"""
    normalized_value = re.sub(r"\s+", "", value or "").strip()
    if _is_section_marker_code(normalized_value):
        return 1
    if _is_dotted_hierarchy_code(normalized_value):
        return normalized_value.count(".") + 1
    return 1 if _is_plain_child_code(normalized_value) else 0


def _parse_markdown_table_rows(table_content: str) -> list[list[str]]:
    """解析 Markdown 表格行，供表内分组识别使用。"""
    lines = [line.strip() for line in table_content.splitlines() if line.strip()]
    if len(lines) < 2 or not all("|" in line for line in lines[:2]):
        return []

    def split_row(line: str) -> list[str]:
        """拆分 Markdown 单行并去除首尾空列。"""
        stripped = line.strip().strip("|")
        return [cell.strip() for cell in stripped.split("|")]

    separator_cells = split_row(lines[1])
    if not separator_cells or not all(re.fullmatch(r":?-{2,}:?", cell) for cell in separator_cells):
        return []
    return [split_row(line) for line in lines]


def _extract_structural_table_rows(table_content: str) -> list[list[str]]:
    """统一取得 HTML/Markdown 表格的逻辑行，避免只支持 HTML 导致分区漏识别。"""
    if re.search(r"<table", table_content or "", flags=re.IGNORECASE):
        parser = _EngineeringTableParser()
        parser.feed(table_content)
        return parser.tables[0] if parser.tables else []
    return _parse_markdown_table_rows(table_content)


def _extract_ordered_structural_tables(context: str) -> list[list[list[str]]]:
    """按原文顺序解析 HTML/Markdown 表格，保证源表索引与模型分块一致。"""
    if not context:
        return []

    table_matches = list(
        re.finditer(r"<table[\s\S]*?</table>", context, flags=re.IGNORECASE)
    )
    table_matches.extend(
        re.finditer(
            r"(?:(?:^|\n)\|[^\n]+\|\n(?:\|[-:\s|]+\|\n)(?:\|[^\n]+\|\n?)+)",
            context,
            flags=re.MULTILINE,
        )
    )

    ordered_tables: list[list[list[str]]] = []
    for table_match in sorted(table_matches, key=lambda match: match.start()):
        rows = _extract_structural_table_rows(table_match.group(0))
        # 即使表格为空也保留占位，确保 source_table_index 与模型上下文中的物理表格索引一致。
        ordered_tables.append(rows)
    return ordered_tables


def _is_markdown_separator_row(cells: list[str]) -> bool:
    """判断 Markdown 表格的分隔行，避免把表头分隔符当成业务清单行。"""
    return bool(cells) and all(
        re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells
    )


def _is_internal_group_row(
    rows: list[list[str]],
    row_index: int,
    code: str,
    cells: list[str],
) -> bool:
    """判断一行是否为表内 BOQ 分组标题，而不是普通计价明细。"""
    if len(cells) < 2 or not code or not cells[1].strip():
        return False
    if _is_section_marker_code(code):
        if _has_explicit_table_measurement(cells):
            return False
        # 独立的根项/编码不能仅凭“没有数量”就判成表内分组，必须找到后续结构行。
        for next_row in rows[row_index + 1 :]:
            next_code = next_row[0].strip() if next_row else ""
            if next_code and _is_section_marker_code(next_code):
                break
            if len(next_row) >= 2 and next_row[1].strip() and (
                _is_plain_child_code(next_code)
                or _is_dotted_hierarchy_code(next_code)
                or _has_explicit_table_measurement(next_row)
            ):
                return True
        return False
    if not (_is_dotted_hierarchy_code(code) or _is_plain_child_code(code)):
        return False
    if _has_explicit_table_measurement(cells):
        return False

    prefix = f"{code}."
    return any(
        len(next_row) >= 1 and next_row[0].strip().startswith(prefix)
        for next_row in rows[row_index + 1 :]
    )


def _source_rows_from_context(context: str) -> list[list[_SourceTableRow]]:
    """从模型实际上下文中提取表格行，供结果层做结构性对齐。"""
    parsed_tables: list[list[_SourceTableRow]] = []
    for table_index, table in enumerate(_extract_ordered_structural_tables(context)):
        if not table:
            continue
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
            if row_index == 0 or (row_index == 1 and _is_markdown_separator_row(cells)):
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


def _normalize_source_bom_parent_name(value: Optional[str]) -> str:
    """清理成套父项名称末尾的组成提示，保留设备本身名称。"""
    normalized_value = (value or "").strip()
    if not normalized_value:
        return ""
    return re.sub(
        r"\s*[,，;；]?\s*每(?:套|台|组|面|项)?\s*(?:包含|含有|包括|配置)\s*[:：]?\s*$",
        "",
        normalized_value,
    ).strip(" ,，;；:")


def _parse_source_composition_components(
    specifications: Optional[str],
) -> list[tuple[str, str, Optional[float], Optional[str]]]:
    """从成套父项的连续规格单元格中拆出有明确文本证据的组成项。"""
    if not specifications or not specifications.strip():
        return []

    components: list[tuple[str, str, Optional[float], Optional[str]]] = []
    pending_component_index: Optional[int] = None
    quantity_pattern = re.compile(
        r"(?:^|[,，\s])(?P<quantity>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>台|套|组|只|面|个|根|米|m|mm|kV|kVA)\s*$",
        re.IGNORECASE,
    )

    def is_specification_continuation(value: str) -> bool:
        """判断无独立物料名称的连续文本是否应并入前一组成项规格。"""
        compact_value = re.sub(r"\s+", "", value)
        if not compact_value:
            return False
        # 不使用项目名称、品牌或型号前缀；仅依据通用技术文本形态判断。
        # 无中文名称、但包含数字/运算符/单位符号的文本通常是型号或参数续行。
        has_chinese = bool(re.search(r"[\u3400-\u9fff]", compact_value))
        has_measurement_syntax = bool(
            re.search(r"\d|[=±×x*/%]", compact_value)
        )
        if not has_chinese and has_measurement_syntax:
            return True
        # 带中文标签的技术属性若没有独立数量，且前面已有待续写节点，
        # 视为前一节点的规格补充；具有明确数量的物料会在主循环中单独创建。
        return bool(
            re.search(r"[:：]", compact_value)
            and not quantity_pattern.search(compact_value)
        ) or bool(
            has_measurement_syntax
            and not re.search(r"[,，]", compact_value)
            and not quantity_pattern.search(compact_value)
        )

    def append_to_pending_component(segment: str) -> bool:
        """将参数续行合并到最近一个尚未闭合的组成项。"""
        if pending_component_index is None or not is_specification_continuation(segment):
            return False
        component_name, component_specification, quantity, unit = components[
            pending_component_index
        ]
        merged_specification = "; ".join(
            part for part in (component_specification, segment) if part
        )
        quantity_match = quantity_pattern.search(segment)
        if quantity_match:
            quantity = float(quantity_match.group("quantity"))
            unit = quantity_match.group("unit")
        components[pending_component_index] = (
            component_name,
            merged_specification,
            quantity,
            unit,
        )
        return True

    for raw_segment in re.split(r"[;；]", specifications):
        segment = raw_segment.strip(" ;；")
        if not segment:
            continue

        quantity_only_match = quantity_pattern.fullmatch(segment)
        if quantity_only_match and pending_component_index is not None:
            component_name, component_specification, _, _ = components[
                pending_component_index
            ]
            quantity = float(quantity_only_match.group("quantity"))
            unit = quantity_only_match.group("unit")
            components[pending_component_index] = (
                component_name,
                f"{component_specification},{segment}"
                if component_specification
                else segment,
                quantity,
                unit,
            )
            pending_component_index = None
            continue

        if append_to_pending_component(segment):
            continue

        bare_name_match = re.fullmatch(r"(?P<name>[^:：]+?)\s*[:：]", segment)
        if bare_name_match:
            # 无数量的组成标题后面通常还有型号和性能参数，先建立待续写节点。
            component_name = bare_name_match.group("name").strip()
            component_specification = ""
            components.append((component_name, component_specification, None, None))
            pending_component_index = len(components) - 1
            continue

        name_match = re.match(r"^(?P<name>[^:：]+?)\s*[:：]\s*(?P<spec>.+)$", segment)
        if name_match:
            component_name = name_match.group("name").strip()
            component_specification = name_match.group("spec").strip()
        else:
            # 部分 OCR 表格使用“组成名称,型号参数”而不是冒号分隔。
            comma_name_match = re.match(
                r"^(?P<name>[^,，]+?)\s*[,，]\s*(?P<spec>.+)$",
                segment,
            )
            if comma_name_match:
                component_name = comma_name_match.group("name").strip()
                component_specification = comma_name_match.group("spec").strip()
            else:
                component_name = segment
                component_specification = segment
        # “具备”是组成描述的谓语，不属于设备/功能项名称。
        component_name = re.sub(r"^(?:具备|包括|含有)\s*", "", component_name).strip()
        if not component_name:
            continue

        quantity_match = quantity_pattern.search(component_specification)
        quantity = (
            float(quantity_match.group("quantity"))
            if quantity_match
            else None
        )
        unit = quantity_match.group("unit") if quantity_match else None
        components.append(
            (component_name, component_specification, quantity, unit)

        )
        pending_component_index = len(components) - 1 if quantity is None else None

    return components


def _source_row_has_real_measurement(row: _SourceTableRow) -> bool:
    """判断源表行是否存在真实计量字段，排除跨列标题被复制出的伪单位。"""
    normalized_name = _normalize_source_cell(row.item_name)
    normalized_unit = _normalize_source_cell(row.unit)
    return row.quantity is not None or bool(
        normalized_unit and normalized_unit != normalized_name
    )


def _unique_source_rows(rows: list[_SourceTableRow]) -> tuple[_SourceTableRow, ...]:
    """按源表字段去重，避免 rowspan 展开后重复绑定同一结构行。"""
    unique_rows: list[_SourceTableRow] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        identity = (
            _normalize_source_cell(row.item_code),
            _normalize_source_cell(row.item_name),
            _normalize_source_cell(row.specifications),
            _normalize_source_cell(row.unit),
            str(row.quantity),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_rows.append(row)
    return tuple(unique_rows)


def _extract_source_structural_candidates(
    table_rows: list[_SourceTableRow],
) -> list[_SourceStructuralCandidate]:
    """识别源表中缺少模型结果的分组、递进编号和 rowspan 父项。"""
    candidates: list[_SourceStructuralCandidate] = []
    seen_candidates: set[tuple[int, str, str, str]] = set()

    def add_candidate(
        row: _SourceTableRow,
        child_rows: tuple[_SourceTableRow, ...],
        candidate_type: Literal["section", "hierarchy", "rowspan"],
    ) -> None:
        """追加候选结构行并按编码、名称和类型去重。"""
        if not child_rows:
            return
        identity = (
            row.row_index,
            _normalize_source_cell(row.item_code),
            _normalize_source_cell(row.item_name),
            candidate_type,
        )
        if identity in seen_candidates:
            return
        seen_candidates.add(identity)
        candidates.append(
            _SourceStructuralCandidate(
                table_index=row.table_index,
                row=row,
                child_rows=child_rows,
                candidate_type=candidate_type,
            )
        )

    # HTML rowspan 展开后，父名称和编码会连续重复；首行是父项，整组行是其规格/组成明细。
    row_index = 0
    while row_index < len(table_rows):
        current_row = table_rows[row_index]
        group_end = row_index + 1
        while group_end < len(table_rows):
            next_row = table_rows[group_end]
            if (
                _normalize_source_cell(next_row.item_code)
                != _normalize_source_cell(current_row.item_code)
                or _normalize_source_cell(next_row.item_name)
                != _normalize_source_cell(current_row.item_name)
            ):
                break
            group_end += 1
        if group_end - row_index >= 2:
            group_rows = table_rows[row_index:group_end]
            distinct_rows = {
                (
                    _normalize_source_cell(row.specifications),
                    _normalize_source_cell(row.unit),
                    str(row.quantity),
                )
                for row in group_rows
            }
            if len(distinct_rows) >= 2:
                # rowspan 父项即使首行带单位，也不能仅按单位把它降级成普通明细。
                add_candidate(current_row, tuple(group_rows), "rowspan")
        row_index = group_end if group_end > row_index + 1 else row_index + 1

    for index, current_row in enumerate(table_rows):
        if _source_row_has_real_measurement(current_row):
            continue

        current_code = current_row.item_code.strip()
        if _is_section_marker_code(current_code):
            if _is_bare_chinese_section_marker(current_code):
                # 不带括号的中文大序号是表内 BOQ 分类，不恢复为 BOM 父项。
                continue
            section_end = len(table_rows)
            for next_index in range(index + 1, len(table_rows)):
                if _is_section_marker_code(table_rows[next_index].item_code):
                    section_end = next_index
                    break
            section_rows = table_rows[index + 1 : section_end]
            # 外层分区下若存在点号层级，交给真实 BOM 修复逻辑处理，避免跨越中间父项挂接。
            if any(_is_dotted_hierarchy_code(row.item_code) for row in section_rows):
                continue
            direct_rows = _unique_source_rows(
                [
                    row
                    for row in section_rows
                    if _is_plain_child_code(row.item_code) and row.item_name.strip()
                ]
            )
            add_candidate(current_row, direct_rows, "section")
            continue

        if not (_is_plain_child_code(current_code) or _is_dotted_hierarchy_code(current_code)):
            continue
        parent_depth = _hierarchy_code_depth(current_code)
        prefix = f"{current_code}."
        direct_rows: list[_SourceTableRow] = []
        for next_row in table_rows[index + 1 :]:
            next_code = next_row.item_code.strip()
            if _is_section_marker_code(next_code):
                break
            if _is_dotted_hierarchy_code(next_code):
                next_depth = _hierarchy_code_depth(next_code)
                if next_depth <= parent_depth:
                    break
                if next_depth == parent_depth + 1 and next_code.startswith(prefix):
                    direct_rows.append(next_row)
                continue
            if _is_plain_child_code(next_code):
                break
        if direct_rows:
            add_candidate(current_row, _unique_source_rows(direct_rows), "hierarchy")

    return sorted(candidates, key=lambda candidate: candidate.row.row_index)


def _source_has_explicit_composition(
    raw_rows: list[list[str]],
    start_row_index: int,
    end_row_index: int,
) -> bool:
    """判断源表分支是否出现明确的成套组成提示。"""
    composition_pattern = re.compile(
        r"每套\s*(?:包含|含有|包括|配置)|组成(?:如下|内容)"
    )
    return any(
        composition_pattern.search("".join(cells))
        for row_index, cells in enumerate(raw_rows)
        if start_row_index <= row_index < end_row_index
    )


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


def _resolve_source_table_index_aliases(
    items: list["EquipmentItem"],
    source_tables: list[list[_SourceTableRow]],
) -> dict[int, int]:
    """将无业务行的物理表索引映射到实际可解析的源清单表索引。"""
    source_table_indexes = {
        table_rows[0].table_index for table_rows in source_tables if table_rows
    }
    model_table_indexes = {
        item.source_table_index
        for item in items
        if item.source_table_index is not None
    }
    aliases: dict[int, int] = {}
    for model_table_index in model_table_indexes:
        if model_table_index in source_table_indexes:
            continue
        candidates: list[tuple[int, int]] = []
        for table_rows in source_tables:
            if not table_rows:
                continue
            table_index = table_rows[0].table_index
            score = 0
            for item in items:
                if item.source_table_index != model_table_index:
                    continue
                item_name = _normalize_source_cell(
                    _normalize_source_bom_parent_name(item.item_name)
                )
                item_code = _normalize_source_cell(item.item_code)
                item_specification = _normalize_source_cell(item.specifications)
                for row in table_rows:
                    row_name = _normalize_source_cell(
                        _normalize_source_bom_parent_name(row.item_name)
                    )
                    if item_name and item_name == row_name:
                        score += 5
                        if item_code and item_code == _normalize_source_cell(row.item_code):
                            score += 3
                        if (
                            item_specification
                            and item_specification
                            == _normalize_source_cell(row.specifications)
                        ):
                            score += 1
                        break
            if score:
                candidates.append((score, table_index))
        if candidates:
            aliases[model_table_index] = max(candidates)[1]

    if aliases:
        logger.info(
            "[EngineeringService] 已修正模型表索引与源表索引偏移：映射=%s",
            aliases,
        )
    return aliases


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


def _get_engineering_chunk_retry_depth() -> int:
    """读取长度超限时允许的递归拆分层数。"""
    raw_depth = os.getenv("ENGINEERING_CHUNK_RETRY_DEPTH", "3")
    try:
        depth = int(raw_depth)
    except ValueError:
        logger.warning(
            "[EngineeringService] ENGINEERING_CHUNK_RETRY_DEPTH 配置无效，将使用默认重试层数。"
        )
        return 3
    return max(min(depth, 6), 0)


def _iter_exception_messages(error: BaseException) -> list[str]:
    """提取异常及其包装异常的文本，兼容重试库包装后的原始异常。"""
    messages: list[str] = []
    visited: set[int] = set()
    pending: list[object] = [error]

    while pending:
        current = pending.pop(0)
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, BaseException):
            messages.append(str(current))
            cause = getattr(current, "__cause__", None)
            context = getattr(current, "__context__", None)
            if cause is not None:
                pending.append(cause)
            if context is not None:
                pending.append(context)
            last_attempt = getattr(current, "last_attempt", None)
            if last_attempt is not None:
                try:
                    last_exception = last_attempt.exception()
                except (AttributeError, RuntimeError):
                    last_exception = None
                if last_exception is not None:
                    pending.append(last_exception)
    return messages


def _is_engineering_length_limit_error(error: BaseException) -> bool:
    """判断异常是否属于模型输出或上下文达到限制，而不是普通业务失败。"""
    error_text = " ".join(_iter_exception_messages(error)).lower()
    limit_markers = (
        "length limit",
        "maximum output",
        "max tokens",
        "context length",
        "token limit",
        "too many tokens",
        "output limit",
        "output token",
    )
    return any(marker in error_text for marker in limit_markers)


def _find_engineering_chunk_tables(chunk_text: str) -> list[re.Match[str]]:
    """定位重试分块中的 HTML 或 Markdown 表格。"""
    html_tables = list(
        re.finditer(r"<table[\s\S]*?</table>", chunk_text, re.IGNORECASE)
    )
    if html_tables:
        return html_tables
    return list(
        re.finditer(
            r"(?:(?:^|\n)\|[^\n]+\|\n(?:\|[-:\s|]+\|\n)(?:\|[^\n]+\|\n?)+)",
            chunk_text,
            re.MULTILINE,
        )
    )


def _split_engineering_chunk_for_retry(
    chunk_text: str,
    grouping_mode: GroupingMode,
) -> list[str]:
    """按完整表格行拆分长度超限分块，并保留表格前置上下文和表头。"""
    table_matches = _find_engineering_chunk_tables(chunk_text)
    if not table_matches:
        return []

    retry_max_chars = max(len(chunk_text) // 2, 1000)
    retry_chunks: list[str] = []
    previous_end = 0
    for table_match in table_matches:
        prefix = chunk_text[previous_end:table_match.start()].strip()
        table_content = table_match.group(0)
        source_rows = _count_table_data_rows(table_content)
        if source_rows <= 1:
            table_parts = [table_content]
        else:
            retry_max_rows = max(source_rows // 2, 1)
            if grouping_mode == "internal":
                # 内部分组重试时重新计算每个子块的当前分组状态，避免跨块继承旧状态。
                table_parts = _build_table_parts_with_internal_group_state(
                    table_content,
                    retry_max_chars,
                    max_rows=retry_max_rows,
                )
            else:
                table_parts = _split_table_preserving_rows(
                    table_content,
                    retry_max_chars,
                    max_rows=retry_max_rows,
                )

        for table_part in table_parts:
            retry_text = f"{prefix}\n\n{table_part}".strip()
            if retry_text and retry_text != chunk_text.strip():
                retry_chunks.append(retry_text)
        previous_end = table_match.end()

    # 最后一张表后可能还有说明文字，将其附着到最后一个子块，尽量保留原始语境。
    tail = chunk_text[previous_end:].strip()
    if tail and retry_chunks:
        candidate = f"{retry_chunks[-1]}\n\n{tail}".strip()
        if len(candidate) <= max(len(chunk_text), retry_max_chars):
            retry_chunks[-1] = candidate

    if len(retry_chunks) <= 1:
        return []
    return retry_chunks


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
    include_internal_group_state: bool = True,
) -> tuple[list[str], list[Optional[str]]]:
    """优先整体提交清单上下文，超限时按完整表格和标题边界聚合拆分。

    ``include_internal_group_state`` 只适用于没有表格外部分区的表格。
    外部分区模式必须保持原始 BOM 上下文，不能把表内目录状态注入模型提示。
    """
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
        if include_internal_group_state:
            table_parts = _build_table_parts_with_internal_group_state(
                table_content,
                max_chars,
                max_rows=source_row_limit,
            )
        else:
            # 外部分区已经承担表格归属，拆分时只保留表头和原始行，
            # 避免内部 BOQ 状态干扰真实 BOM 父子关系。
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
    table_grouping_modes: Optional[dict[int, GroupingMode]] = None,
    table_section_titles: Optional[list[Optional[str]]] = None,
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
    carried_group_state: list[tuple[str, str]] = []
    previous_table_content: Optional[str] = None
    previous_grouping_mode: Optional[GroupingMode] = None

    for table_index, table_match in enumerate(table_matches):
        heading = clean_context[last_end:table_match.start()].strip()
        section_title = (
            table_section_titles[table_index]
            if table_section_titles and table_index < len(table_section_titles)
            else extract_engineering_section_name_from_heading(heading)
        )
        grouping_mode = (
            table_grouping_modes.get(table_index)
            if table_grouping_modes
            else resolve_engineering_table_grouping_mode(
                section_title,
                table_match.group(0),
            )
        )
        is_external_grouping = grouping_mode == "external"

        is_internal_continuation = bool(
            previous_table_content
            and previous_grouping_mode == "internal"
            and _is_likely_internal_table_continuation(
                previous_table_content,
                table_match.group(0),
                carried_group_state,
            )
        )
        if carried_group_state and not is_internal_continuation:
            logger.info(
                "[EngineeringService] 当前表格未通过表内续表校验，已清除跨表分组状态：table_index=%d",
                table_index,
            )
            carried_group_state = []
        if grouping_mode == "none" and is_internal_continuation:
            # 续表虽然自身没有重复分组行，但语义上仍属于上一张表内分组清单。
            grouping_mode = "internal"
            if table_grouping_modes is not None:
                table_grouping_modes[table_index] = "internal"
            logger.info(
                "[EngineeringService] 已将物理续表归入表内分组模式：table_index=%d",
                table_index,
            )
        if is_external_grouping:
            # 表外分区模式与表内分组模式严格隔离，外部标题不应触发表内状态继承。
            table_parts = _split_table_preserving_rows(
                table_match.group(0),
                max_chars,
                max_rows=_get_engineering_source_row_limit(),
            )
        else:
            table_parts = _build_table_parts_with_internal_group_state(
                table_match.group(0),
                max_chars,
                max_rows=_get_engineering_source_row_limit(),
                initial_state=carried_group_state,
            )
        for table_part in table_parts:
            chunk_text = f"{heading}\n\n{table_part}".strip()
            chunks.append(chunk_text)
            chunk_sections.append(section_title)
            chunk_table_indexes.append(table_index)
        carried_group_state = (
            []
            if is_external_grouping
            else _get_internal_group_state_after_table(
                table_match.group(0),
                initial_state=carried_group_state,
            )
        )
        previous_table_content = table_match.group(0)
        previous_grouping_mode = grouping_mode
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
        elif starts_broad_number and re.search(r"标段|分标|区域|分区|分项|部分|地块|厂区|工区|工业|园区|系统", title_clean):
            # 中文大序号只有在标题本身明确表达分区/标段语义时才保留。
            segment_heading_candidates.append(normalized_title)
        elif (
            not starts_broad_number
            and len(normalized_title) <= 40
            and re.search(r"标段|分标|区域|分区|分项|部分|地块|厂区|工区|工业|园区|系统", normalized_title)
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
    """从当前表格结构中找出中文大序号和递进编码分组。"""
    if not table_content:
        return []

    rows = _extract_structural_table_rows(table_content)
    if not rows:
        return []

    candidates: list[tuple[str, str]] = []
    for row_index, cells in enumerate(rows):
        if len(cells) < 2:
            continue
        code = cells[0].strip()
        name = cells[1].strip()
        if not code or not name:
            continue

        if _is_internal_group_row(rows, row_index, code, cells):
            candidates.append((code, name))
    return candidates


def _build_internal_group_states(
    table_content: str,
    table_parts: list[str],
    initial_state: Optional[list[tuple[str, str]]] = None,
) -> list[list[tuple[str, str]]]:
    """为每个表格分块保存分块开始前的表内分组状态，支持跨页继承。"""
    all_rows = _extract_structural_table_rows(table_content)
    if not all_rows or not table_parts:
        return [[] for _ in table_parts]

    candidates = {
        code: (code, name, _hierarchy_code_depth(code))
        for code, name in _extract_inner_section_candidates(table_content)
    }
    active_groups: dict[int, tuple[str, str]] = {
        _hierarchy_code_depth(code): (code, name)
        for code, name in (initial_state or [])
        if _hierarchy_code_depth(code) > 0
    }
    states: list[list[tuple[str, str]]] = []

    for part in table_parts:
        states.append(
            [active_groups[level] for level in sorted(active_groups)]
        )
        part_rows = _extract_structural_table_rows(part)
        for row_index, cells in enumerate(part_rows):
            if not cells:
                continue
            code = cells[0].strip()
            if not code or code in {"序号", "编号", "编码"}:
                continue
            candidate = candidates.get(code)
            if candidate:
                _, name, level = candidate
                active_groups = {
                    current_level: value
                    for current_level, value in active_groups.items()
                    if current_level < level
                }
                active_groups[level] = (code, name)
                continue

            # 普通整数编号在“中文大序号 + 分组名称”这类结构下通常是计价明细，
            # 不能据此清空中文大序号；点号编码才代表新的递进目录边界。
            if _is_dotted_hierarchy_code(code):
                level = _hierarchy_code_depth(code)
                active_groups = {
                    current_level: value
                    for current_level, value in active_groups.items()
                    if current_level < level
                }

    return states


def _get_internal_group_state_after_table(
    table_content: str,
    initial_state: Optional[list[tuple[str, str]]] = None,
) -> list[tuple[str, str]]:
    """计算当前表格处理结束后的分组状态，供下一页表格片段继承。"""
    rows = _extract_structural_table_rows(table_content)
    if not rows:
        return list(initial_state or [])

    candidates = {
        code: (code, name, _hierarchy_code_depth(code))
        for code, name in _extract_inner_section_candidates(table_content)
    }
    active_groups: dict[int, tuple[str, str]] = {
        _hierarchy_code_depth(code): (code, name)
        for code, name in (initial_state or [])
        if _hierarchy_code_depth(code) > 0
    }
    for row_index, cells in enumerate(rows):
        if not cells:
            continue
        code = cells[0].strip()
        if not code or code in {"序号", "编号", "编码"}:
            continue
        candidate = candidates.get(code)
        if candidate:
            _, name, level = candidate
            active_groups = {
                current_level: value
                for current_level, value in active_groups.items()
                if current_level < level
            }
            active_groups[level] = (code, name)
        elif _is_dotted_hierarchy_code(code):
            level = _hierarchy_code_depth(code)
            active_groups = {
                current_level: value
                for current_level, value in active_groups.items()
                if current_level < level
            }

    return [active_groups[level] for level in sorted(active_groups)]


def _format_internal_group_state(state: list[tuple[str, str]]) -> str:
    """将跨分块继承的表内分组状态格式化为模型可读的提示。"""
    if not state:
        return ""
    groups = "；".join(f"编码 {code} / 名称 {name}" for code, name in state)
    return (
        "【表内分区状态（由当前表格前序行继承）】\n"
        f"当前分块开始时的有效分组：{groups}\n"
        "该状态只用于把当前分块中的明细归入原文分组，不是新增清单行。"
    )


def _should_carry_internal_group_state(
    table_content: str,
    carried_state: list[tuple[str, str]],
) -> bool:
    """判断独立表格片段是否仍属于上一张工程量清单表。

    PDF 转 HTML 后，分页可能把同一张清单拆成多个 ``table``；但同一章节
    后面也可能紧跟其他类型的非计量表。不能只依据“相邻”关系继承分组状态，
    需要同时检查表头和数据行形态，避免把无关表格污染到当前清单。
    """
    if not carried_state:
        return False

    rows = _extract_structural_table_rows(table_content)
    if not rows:
        logger.debug("[EngineeringService] 当前表格片段无可解析行，停止继承表内分组状态")
        return False

    first_rows = rows[:3]
    first_text = " ".join(" ".join(cell for cell in row) for row in first_rows)
    has_dotted_or_section_code = any(
        cells
        and (
            _is_dotted_hierarchy_code(cells[0].strip())
            or _is_section_marker_code(cells[0].strip())
        )
        for cells in rows[1:]
    )

    if has_dotted_or_section_code:
        return True

    # 不依赖列名判断计量列：分页续表通常仍保留稳定的尾部数值列，
    # 且数值前至少有两列有效载荷；名单类表格的序号通常位于前部，
    # 不满足这种列形状，因此会被自动断开。
    trailing_numeric_positions: list[int] = []
    for cells in rows:
        if len(cells) < 4:
            continue
        trailing_start = max(len(cells) - 2, 2)
        for cell_index, cell in enumerate(cells):
            if cell_index < trailing_start:
                continue
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell.replace(",", "")):
                non_empty_before = sum(bool(value.strip()) for value in cells[:cell_index])
                if non_empty_before >= 2:
                    trailing_numeric_positions.append(cell_index)
                    break

    if trailing_numeric_positions:
        return True

    logger.debug(
        "[EngineeringService] 当前表格缺少连续计量列形态，停止继承表内分组状态：首行=%s",
        first_text[:120],
    )
    return False


def _has_repeated_table_header(previous_table: str, current_table: str) -> bool:
    """判断相邻物理表格是否保留了相同的原始表头结构。"""
    previous_rows = _extract_structural_table_rows(previous_table)
    current_rows = _extract_structural_table_rows(current_table)
    if not previous_rows or not current_rows:
        return False

    previous_header = tuple(_normalize_source_cell(cell) for cell in previous_rows[0])
    current_header = tuple(_normalize_source_cell(cell) for cell in current_rows[0])
    return bool(previous_header and previous_header == current_header)


def _is_likely_internal_table_continuation(
    previous_table: str,
    current_table: str,
    carried_state: list[tuple[str, str]],
) -> bool:
    """依据重复表头和首行编码确认表内分组的分页续表。"""
    if not carried_state or not _has_repeated_table_header(previous_table, current_table):
        return False

    current_rows = _extract_structural_table_rows(current_table)
    first_data_code = next(
        (
            row[0].strip()
            for row in current_rows[1:]
            if row and row[0].strip()
        ),
        "",
    )
    if not first_data_code:
        return True
    if not _is_dotted_hierarchy_code(first_data_code):
        return False
    return any(
        first_data_code.startswith(f"{code}.") or first_data_code == code
        for code, _ in carried_state
    )


def _is_likely_external_table_continuation(
    previous_table: str,
    current_table: str,
) -> bool:
    """依据表头和首个数据编码识别外部分区下的分页续表。"""
    if not _has_repeated_table_header(previous_table, current_table):
        return False

    current_rows = _extract_structural_table_rows(current_table)
    first_data_code = next(
        (
            row[0].strip()
            for row in current_rows[1:]
            if row and row[0].strip()
        ),
        "",
    )
    # 点号编码通常表示当前表格从上一页的层级继续；首列为空则表示续表未重复序号。
    if not first_data_code or _is_dotted_hierarchy_code(first_data_code):
        return True
    if not _is_plain_child_code(first_data_code):
        return False

    previous_rows = _extract_structural_table_rows(previous_table)
    previous_data_codes = [
        row[0].strip()
        for row in previous_rows[1:]
        if row and _is_plain_child_code(row[0].strip())
    ]
    if not previous_data_codes:
        return False
    # 普通整数续表只在当前编号严格大于上一页末编号时继承，避免把新表的“1”误接到旧分区。
    return int(first_data_code) > int(previous_data_codes[-1])


def _extract_section_evidence_from_heading(
    heading_text: str,
    section_name: Optional[str],
) -> Optional[str]:
    """从表格前置文本提取可逐字回溯的最短分区证据片段。"""
    if not heading_text or not section_name:
        return None
    compact_section = re.sub(r"\s+", "", section_name)
    for line in reversed([item.strip() for item in heading_text.splitlines() if item.strip()]):
        if compact_section and compact_section in re.sub(r"\s+", "", line):
            # section_name 是从该原文行中归一化得到的连续片段，保留其文本本身，
            # 避免把 Markdown 标题符号或整句说明写入结构化证据字段。
            return section_name
    return None


def _inherit_external_table_context(
    table_matches: list[re.Match[str]],
    table_section_titles: list[Optional[str]],
    table_section_evidences: list[Optional[str]],
    table_grouping_modes: dict[int, GroupingMode],
) -> None:
    """把可验证的外部分区上下文传递给分页续表，不混入表内分组状态。"""
    for table_index in range(1, len(table_matches)):
        previous_index = table_index - 1
        if table_grouping_modes.get(previous_index) != "external":
            continue
        if table_section_titles[table_index]:
            continue
        if not _is_likely_external_table_continuation(
            table_matches[previous_index].group(0),
            table_matches[table_index].group(0),
        ):
            continue

        previous_section = table_section_titles[previous_index]
        if not previous_section:
            continue
        table_section_titles[table_index] = previous_section
        table_section_evidences[table_index] = table_section_evidences[previous_index]
        table_grouping_modes[table_index] = "external"
        logger.info(
            "[EngineeringService] 已将相邻续表归入同一外部分区：物理表格=%d，继承自=%d",
            table_index,
            previous_index,
        )


def _collect_source_measurement_names(source_context: str) -> list[str]:
    """从原始表格结构中统计有尾部数值载荷的清单行名称。

    该审计只读取原文，不负责补造模型结果；用途是区分“模型漏提明细”
    与“原文无计量的目录标题未作为成本项输出”，并且不依赖固定表头或业务词表。
    """
    source_names: list[str] = []
    for rows in _extract_ordered_structural_tables(source_context or ""):
        for row_index, cells in enumerate(rows):
            if row_index == 0 or (row_index == 1 and _is_markdown_separator_row(cells)):
                continue
            if len(cells) < 4:
                continue
            trailing_start = max(len(cells) - 2, 2)
            numeric_index = next(
                (
                    index
                    for index in range(len(cells) - 1, trailing_start - 1, -1)
                    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cells[index].replace(",", ""))
                ),
                None,
            )
            if numeric_index is None:
                continue
            if sum(bool(value.strip()) for value in cells[:numeric_index]) < 2:
                continue
            item_name = cells[1].strip() if len(cells) > 1 and cells[1].strip() else ""
            if not item_name:
                item_name = next((value.strip() for value in cells[:numeric_index] if value.strip()), "")
            if item_name:
                source_names.append(_normalize_source_cell(item_name))
    return source_names


def _build_table_parts_with_internal_group_state(
    table_content: str,
    max_chars: int,
    max_rows: Optional[int],
    initial_state: Optional[list[tuple[str, str]]] = None,
) -> list[str]:
    """拆分表格并把前序表内分组状态带入每个分块。"""
    table_parts = _split_table_preserving_rows(
        table_content,
        max_chars,
        max_rows=max_rows,
    )
    states = _build_internal_group_states(table_content, table_parts, initial_state=initial_state)
    inherited_state_count = sum(bool(state) for state in states)
    if inherited_state_count:
        logger.debug(
            "[EngineeringService] 已向表格分块继承表内分组状态：分块数=%d，带状态分块数=%d",
            len(table_parts),
            inherited_state_count,
        )
    contextual_parts: list[str] = []
    for table_part, state in zip(table_parts, states):
        state_text = _format_internal_group_state(state)
        contextual_parts.append(f"{state_text}\n\n{table_part}".strip() if state_text else table_part)
    return contextual_parts


def build_engineering_table_section_hints(
    clean_context: str,
    table_matches: list[re.Match[str]],
    table_grouping_modes: Optional[dict[int, GroupingMode]] = None,
    table_section_titles: Optional[list[Optional[str]]] = None,
) -> list[str]:
    """为每张清单表生成由原文标题推导的分区定位提示，避免多表上下文互相串区。

    已确认表格外部分区时，不向模型暴露表内分组候选，避免两种语义在同一
    个提取任务中竞争；未确认外部分区时，才提供表内分组的结构提示。
    """
    if not clean_context or not table_matches:
        return []

    hints: list[str] = []
    last_end = 0
    for display_index, table_match in enumerate(table_matches, start=1):
        table_index = display_index - 1
        heading = clean_context[last_end:table_match.start()].strip()
        section_name = (
            table_section_titles[table_index]
            if table_section_titles and table_index < len(table_section_titles)
            else extract_engineering_section_name_from_heading(heading)
        )
        grouping_mode = (
            table_grouping_modes.get(table_index)
            if table_grouping_modes
            else None
        )
        if section_name:
            # 仅传递当前表格前的真实原文，模型必须从该证据中作最终判断。
            heading_lines = [line.strip() for line in heading.splitlines() if line.strip()]
            evidence = next(
                (line for line in reversed(heading_lines) if section_name in line),
                section_name,
            )
            hint = f"- 表格 {display_index}：外层候选分区={section_name}；原文标题证据={evidence}"
        else:
            hint = f"- 表格 {display_index}：未从表格前置标题确认分区，必须返回 null 或依据表内独立分区文字判断"

        if grouping_mode == "external":
            hints.append(hint)
            last_end = table_match.end()
            continue

        inner_candidates = _extract_inner_section_candidates(table_match.group(0))
        if inner_candidates:
            inner_text = "；".join(
                f"编码 {code} / 名称 {name}"
                for code, name in inner_candidates
            )
            hint += (
                f"\n  表内更具体分组候选（优先写入 part_name/group_path，不得覆盖 section_name，也不得直接作为 parent_item）：{inner_text}"
                "\n  对无数量、无单位且后续存在递进编码子行的候选，默认是 BOQ 分类标题；"
                "只有出现明确成套组成证据时，才作为 BOM 结构父节点。"
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


def resolve_engineering_table_grouping_mode(
    section_name: Optional[str],
    table_content: str,
) -> GroupingMode:
    """根据当前原始表格的结构确定唯一主分组模式。

    表格前置标题和表内目录是两种不同的上下文。若当前表同时出现两者，
    前置标题优先作为本表展示分组，只有无法确认前置标题时才使用表内目录，
    避免同一张表在页面上生成两套并行分组控件。判断过程只读取原文结构，
    不匹配具体项目名称。
    """
    has_internal_groups = bool(_extract_inner_section_candidates(table_content))
    has_external_section = bool(
        section_name and is_valid_engineering_section_name(section_name)
    )
    if has_external_section:
        return "external"
    if has_internal_groups:
        return "internal"
    return "none"


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



def _equipment_item_identity(item: EquipmentItem) -> tuple[object, ...]:
    """生成有可靠原始编码的重试结果去重键。"""
    return (
        item.source_table_index,
        _normalize_source_cell(item.item_code),
        _normalize_source_cell(item.item_name),
        _normalize_source_cell(item.specifications),
        _normalize_source_cell(item.unit),
        item.quantity,
    )


def _merge_equipment_item_metadata(
    current: EquipmentItem,
    candidate: EquipmentItem,
) -> None:
    """合并同一来源行的补充字段，避免重试结果覆盖已有有效信息。"""
    optional_fields = (
        "brand_requirements",
        "parent_item",
        "root_item",
        "section_name",
        "section_evidence",
        "part_name",
    )
    for field_name in optional_fields:
        current_value = getattr(current, field_name)
        candidate_value = getattr(candidate, field_name)
        if not current_value and candidate_value:
            setattr(current, field_name, candidate_value)

    if current.tree_level == 1 and candidate.tree_level not in (None, 1):
        current.tree_level = candidate.tree_level
    if current.per_set_quantity is None and candidate.per_set_quantity is not None:
        current.per_set_quantity = candidate.per_set_quantity
    if not current.group_path and candidate.group_path:
        current.group_path = list(candidate.group_path)
    # 模型允许关键参数为空，合并前统一转换为空列表，避免 None 被当作可迭代对象。
    current_parameters = list(current.key_parameters or [])
    candidate_parameters = list(candidate.key_parameters or [])
    for parameter in candidate_parameters:
        if parameter not in current_parameters:
            current_parameters.append(parameter)
    current.key_parameters = current_parameters


def _deduplicate_equipment_items(items: list[EquipmentItem]) -> list[EquipmentItem]:
    """按来源字段和 BOM 分支合并重复项，无编码行保持独立。"""
    unique_items: list[EquipmentItem] = []
    item_positions: dict[tuple[object, ...], list[int]] = {}

    def same_bom_branch(current: EquipmentItem, candidate: EquipmentItem) -> bool:
        """仅合并同一根项、同一直接父项下的重复节点。"""
        for field_name in ("root_item", "parent_item"):
            current_value = _normalize_source_cell(getattr(current, field_name))
            candidate_value = _normalize_source_cell(getattr(candidate, field_name))
            if current_value and candidate_value and current_value != candidate_value:
                return False
        current_level = current.tree_level or 1
        candidate_level = candidate.tree_level or 1
        if current_level > 1 and candidate_level > 1 and current_level != candidate_level:
            return False
        return True

    for item in items:
        # 没有原始编码时无法证明两行来自同一来源行，不能用相同内容代替行身份。
        # 这类清单中出现名称、规格、单位和数量完全相同的并列项是合法情况，必须全部保留。
        if not _normalize_source_cell(item.item_code):
            unique_items.append(item)
            continue
        identity = _equipment_item_identity(item)
        compatible_position = next(
            (
                position
                for position in item_positions.get(identity, [])
                if same_bom_branch(unique_items[position], item)
            ),
            None,
        )
        if compatible_position is None:
            item_positions.setdefault(identity, []).append(len(unique_items))
            unique_items.append(item)
            continue
        _merge_equipment_item_metadata(unique_items[compatible_position], item)
    return unique_items


# 显式导出私有辅助函数，保持历史测试和服务模块的兼容导入路径。
__all__ = [
    name
    for name, value in globals().items()
    if (name.startswith("_") and not name.startswith("__"))
    or callable(value)
    or name == "GroupingMode"
]
