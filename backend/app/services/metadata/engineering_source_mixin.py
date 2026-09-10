from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional

from pydantic import BaseModel

from .engineering_helpers import (
    _SourceStructuralCandidate,
    _SourceTableRow,
    _assign_items_to_source_tables,
    _extract_ordered_structural_tables,
    _extract_source_structural_candidates,
    _is_bare_chinese_section_marker,
    _is_dotted_hierarchy_code,
    _is_plain_child_code,
    _is_section_marker_code,
    _normalize_source_bom_parent_name,
    _normalize_source_cell,
    _parse_source_composition_components,
    _resolve_source_table_index_aliases,
    _source_has_explicit_composition,
    _source_row_has_real_measurement,
    _source_rows_from_context,
)
from .engineering_helpers import *  # noqa: F401,F403，复用工程清单通用辅助函数
from .engineering_models import EquipmentItem

logger = logging.getLogger(__name__)

class EngineeringSourceRepairMixin:
    @staticmethod
    def _repair_boq_hierarchy_from_source(
        items: list[EquipmentItem],
        source_context: str,
        item_table_indexes: Optional[dict[int, int]] = None,
        allowed_table_indexes: Optional[set[int]] = None,
        table_grouping_modes: Optional[dict[int, GroupingMode]] = None,
        preserve_unpriced_structural_nodes: bool = False,
    ) -> list[EquipmentItem]:
        """依据完整表格的结构边界补齐模型遗漏的分组父项。

        大模型负责语义抽取，但可能遗漏视觉上像分类标题的计价分组行。
        这里不识别任何具体项目名称，只使用原始表格的括号编码、列结构、
        明细编码和“下一个同级编码为边界”等通用证据恢复父子关系。

        ``allowed_table_indexes`` 用于把恢复范围限定到指定原始表格，
        ``table_grouping_modes`` 用于让补回行继承后端确定的主分组模式。
        ``preserve_unpriced_structural_nodes`` 仅用于保留无计量但明确承载子项的结构行。
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

        source_table_aliases = _resolve_source_table_index_aliases(
            items, source_tables
        )
        for item in items:
            mapped_table_index = item_table_indexes.get(id(item))
            if mapped_table_index in source_table_aliases:
                item_table_indexes[id(item)] = source_table_aliases[mapped_table_index]
        effective_allowed_table_indexes = (
            {
                source_table_aliases.get(table_index, table_index)
                for table_index in allowed_table_indexes
            }
            if allowed_table_indexes is not None
            else None
        )

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
        repaired_structural_count = 0
        repaired_child_count = 0
        cleared_boundary_count = 0

        for table_rows in source_tables:
            if not table_rows:
                continue
            # 使用原始表格编号与模型分块的表格归属保持一致。
            table_index = table_rows[0].table_index
            if (
                effective_allowed_table_indexes is not None
                and table_index not in effective_allowed_table_indexes
            ):
                continue
            marker_positions = [
                index
                for index, row in enumerate(table_rows)
                if _is_section_marker_code(row.item_code)
            ]
            for marker_offset, marker_index in enumerate(marker_positions):
                section_row = table_rows[marker_index]
                if _is_bare_chinese_section_marker(section_row.item_code):
                    # 中文大序号仅表示表内分类，不能在外部分区中生成 BOM 根项。
                    continue
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
                            root_item=section_row.item_name.strip(),
                            tree_level=1,
                            source_table_index=table_index,
                            grouping_mode=(
                                table_grouping_modes.get(table_index, "none")
                                if table_grouping_modes
                                else "none"
                            ),
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
                elif preserve_unpriced_structural_nodes:
                    # 外部分区表中的无计量分组行仍可能是原文明确的结构节点；
                    # 保留它用于展示层级，但不填充计量数据，避免进入价格匹配。
                    if parent_index is None:
                        first_child_index = min(matched_children)
                        first_child = items[first_child_index]
                        parent_item = EquipmentItem(
                            item_code=section_row.item_code,
                            item_name=section_row.item_name,
                            specifications=section_row.specifications,
                            section_name=first_child.section_name,
                            root_item=section_row.item_name.strip(),
                            tree_level=1,
                            source_table_index=table_index,
                            grouping_mode=(
                                table_grouping_modes.get(table_index, "none")
                                if table_grouping_modes
                                else "none"
                            ),
                        )
                        insertions.setdefault(first_child_index, []).append(parent_item)
                        if item_table_indexes is not None:
                            item_table_indexes[id(parent_item)] = table_index
                        parent_name = parent_item.item_name.strip()
                        repaired_structural_count += 1
                    else:
                        used_indexes.add(parent_index)
                        structural_parent = items[parent_index]
                        parent_name = structural_parent.item_name.strip()
                        structural_parent.parent_item = None
                        structural_parent.root_item = parent_name
                        structural_parent.tree_level = 1
                        structural_parent.per_set_quantity = None

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

        if repaired_parent_count or repaired_structural_count or repaired_child_count or cleared_boundary_count:
            logger.info(
                "[EngineeringService] 按原始表格结构修复清单层级："
                f"补回计价分组父项={repaired_parent_count}，"
                f"保留无计量结构节点={repaired_structural_count}，"
                f"绑定分组明细={repaired_child_count}，"
                f"清理边界串挂={cleared_boundary_count}"
            )
        return items

    @staticmethod
    def _remove_unpriced_external_boq_group_rows_from_source(
        items: list[EquipmentItem],
        source_context: str,
        item_table_indexes: Optional[dict[int, int]] = None,
        allowed_table_indexes: Optional[set[int]] = None,
    ) -> list[EquipmentItem]:
        """移除外部分区表中被模型误提取的中文大序号分类行。"""
        if not items or not source_context:
            return items

        source_tables = _source_rows_from_context(source_context)
        if not source_tables:
            return items
        if item_table_indexes is None:
            assignments, _ = _assign_items_to_source_tables(items, source_tables)
            item_table_indexes = {
                id(items[item_index]): table_index
                for item_index, table_index in assignments.items()
            }
        source_table_aliases = _resolve_source_table_index_aliases(
            items, source_tables
        )
        for item in items:
            mapped_table_index = item_table_indexes.get(id(item))
            if mapped_table_index in source_table_aliases:
                item_table_indexes[id(item)] = source_table_aliases[mapped_table_index]
        effective_allowed_table_indexes = (
            {
                source_table_aliases.get(table_index, table_index)
                for table_index in allowed_table_indexes
            }
            if allowed_table_indexes is not None
            else None
        )

        def item_key(value: Optional[str]) -> str:
            """统一模型字段和源表字段的匹配格式。"""
            return _normalize_source_cell(value)

        def item_table_index(item: EquipmentItem) -> Optional[int]:
            """读取后处理维护的表格归属。"""
            if item_table_indexes is not None and id(item) in item_table_indexes:
                return item_table_indexes[id(item)]
            return item.source_table_index

        dropped_ids: set[int] = set()
        dropped_names: set[str] = set()
        cleared_relation_count = 0
        for table_rows in source_tables:
            if not table_rows:
                continue
            table_index = table_rows[0].table_index
            if (
                effective_allowed_table_indexes is not None
                and table_index not in effective_allowed_table_indexes
            ):
                continue
            for source_row in table_rows:
                if not _is_bare_chinese_section_marker(source_row.item_code):
                    continue
                if _source_row_has_real_measurement(source_row):
                    continue
                for item in items:
                    if item_table_index(item) != table_index:
                        continue
                    if item_key(item.item_name) != item_key(source_row.item_name):
                        continue
                    model_code = item_key(item.item_code)
                    source_code = item_key(source_row.item_code)
                    if model_code and model_code != source_code:
                        continue
                    dropped_ids.add(id(item))
                    dropped_names.add(item_key(item.item_name))

        if not dropped_ids:
            return items

        # 分类行被移除后，清理模型可能基于该分类误建的父子字段，避免留下悬空根项。
        for item in items:
            if id(item) in dropped_ids:
                continue
            if item_key(item.parent_item) in dropped_names:
                item.parent_item = None
                item.tree_level = 1
                item.per_set_quantity = None
                cleared_relation_count += 1
            if item_key(item.root_item) in dropped_names:
                item.root_item = None
                cleared_relation_count += 1

        logger.info(
            "[EngineeringService] 外部分区移除无计量中文 BOQ 分类行：移除=%d，清理分类关联=%d",
            len(dropped_ids),
            cleared_relation_count,
        )
        return [item for item in items if id(item) not in dropped_ids]

    @staticmethod
    def _restore_missing_structural_nodes_from_source(
        items: list[EquipmentItem],
        source_context: str,
        item_table_indexes: Optional[dict[int, int]] = None,
        allowed_table_indexes: Optional[set[int]] = None,
        table_grouping_modes: Optional[dict[int, GroupingMode]] = None,
    ) -> list[EquipmentItem]:
        """恢复模型遗漏的递进编号父项和 rowspan 合并名称，并绑定其直接子项。"""
        if not items or not source_context:
            return items

        source_tables = _source_rows_from_context(source_context)
        raw_tables = _extract_ordered_structural_tables(source_context)
        if not source_tables:
            logger.debug("[EngineeringService] 无源表行可用于结构父项恢复。")
            return items
        if item_table_indexes is None:
            assignments, _ = _assign_items_to_source_tables(items, source_tables)
            item_table_indexes = {
                id(items[item_index]): table_index
                for item_index, table_index in assignments.items()
            }
        source_table_aliases = _resolve_source_table_index_aliases(
            items, source_tables
        )
        for item in items:
            mapped_table_index = item_table_indexes.get(id(item))
            if mapped_table_index in source_table_aliases:
                item_table_indexes[id(item)] = source_table_aliases[mapped_table_index]
        effective_allowed_table_indexes = (
            {
                source_table_aliases.get(table_index, table_index)
                for table_index in allowed_table_indexes
            }
            if allowed_table_indexes is not None
            else None
        )

        def item_key(value: Optional[str]) -> str:
            """统一模型字段和源表字段的匹配格式。"""
            return _normalize_source_cell(value)

        def item_table_index(item: EquipmentItem) -> Optional[int]:
            """读取后处理维护的表格归属，兼容旧调用方未传映射的情况。"""
            if item_table_indexes is not None and id(item) in item_table_indexes:
                return item_table_indexes[id(item)]
            return item.source_table_index

        def find_matching_item(
            source_row: _SourceTableRow,
            table_index: int,
            allow_specification_name: bool = False,
            exclude_item: Optional[EquipmentItem] = None,
        ) -> Optional[EquipmentItem]:
            """按名称、编码及 rowspan 规格名称寻找当前表格中的模型项。"""
            source_code = item_key(source_row.item_code)
            source_name = item_key(source_row.item_name)
            source_specification = item_key(source_row.specifications)
            candidates: list[tuple[int, int, EquipmentItem]] = []
            for position, item in enumerate(working_items):
                if exclude_item is not None and item is exclude_item:
                    continue
                if item_table_index(item) != table_index:
                    continue
                model_name = item_key(item.item_name)
                if model_name == source_name:
                    score = 30
                elif allow_specification_name and source_specification and model_name == source_specification:
                    score = 20
                else:
                    continue
                model_code = item_key(item.item_code)
                if model_code and source_code and model_code != source_code:
                    continue
                if model_code and source_code and model_code == source_code:
                    score += 10
                if source_row.unit and item_key(item.unit) == item_key(source_row.unit):
                    score += 3
                candidates.append((score, -position, item))
            if not candidates:
                return None
            return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]

        def source_position(item: EquipmentItem, table_rows: list[_SourceTableRow]) -> Optional[int]:
            """定位模型项在源表中的首个可能行，用于按原文顺序插入恢复节点。"""
            model_name = item_key(item.item_name)
            model_code = item_key(item.item_code)
            positions: list[int] = []
            for row in table_rows:
                if model_code and item_key(row.item_code) != model_code:
                    continue
                if model_name in {item_key(row.item_name), item_key(row.specifications)}:
                    positions.append(row.row_index)
            return min(positions) if positions else None

        working_items = list(items)
        candidate_nodes: list[tuple[_SourceStructuralCandidate, EquipmentItem]] = []
        recovered_parent_count = 0
        bound_child_count = 0
        skipped_explicit_candidate_count = 0

        def candidate_has_explicit_bom_evidence(
            candidate: _SourceStructuralCandidate,
            table_rows: list[_SourceTableRow],
        ) -> bool:
            """判断结构候选是否位于已有明确成套证据的括号分支。"""
            marker_positions = [
                index
                for index, row in enumerate(table_rows)
                if _is_section_marker_code(row.item_code)
            ]
            candidate_position = next(
                (
                    index
                    for index, row in enumerate(table_rows)
                    if row.row_index == candidate.row.row_index
                ),
                None,
            )
            if candidate_position is None or not marker_positions:
                return False
            previous_markers = [
                marker_index
                for marker_index in marker_positions
                if marker_index <= candidate_position
            ]
            if not previous_markers:
                return False
            marker_position = previous_markers[-1]
            marker_row = table_rows[marker_position]
            marker_offset = marker_positions.index(marker_position)
            next_position = (
                marker_positions[marker_offset + 1]
                if marker_offset + 1 < len(marker_positions)
                else len(table_rows)
            )
            raw_table_index = table_rows[0].table_index
            if raw_table_index >= len(raw_tables):
                return False
            end_row_index = (
                table_rows[next_position].row_index
                if next_position < len(table_rows)
                else len(raw_tables[raw_table_index])
            )
            return _source_has_explicit_composition(
                raw_tables[raw_table_index],
                marker_row.row_index,
                end_row_index,
            )

        for table_rows in source_tables:
            if not table_rows:
                continue
            table_index = table_rows[0].table_index
            if (
                effective_allowed_table_indexes is not None
                and table_index not in effective_allowed_table_indexes
            ):
                continue
            if not any(item_table_index(item) == table_index for item in items):
                # 与空结果保护一致：没有任何模型证据时，不按源表批量生成清单。
                continue

            table_candidates = _extract_source_structural_candidates(table_rows)
            for candidate in table_candidates:
                if candidate_has_explicit_bom_evidence(candidate, table_rows):
                    # 明确 BOM 统一由后续源表逐分支恢复，避免旧的全表同名匹配制造重复节点。
                    skipped_explicit_candidate_count += 1
                    continue
                parent_item = find_matching_item(candidate.row, table_index)
                if parent_item is None:
                    context_item = next(
                        (
                            item
                            for item in working_items
                            if item_table_index(item) == table_index
                        ),
                        None,
                    )
                    parent_item = EquipmentItem(
                        item_code=candidate.row.item_code,
                        item_name=candidate.row.item_name,
                        specifications=None,
                        quantity=None,
                        unit=None,
                        section_name=context_item.section_name if context_item else None,
                        section_evidence=(
                            context_item.section_evidence
                            if context_item
                            else None
                        ),
                        root_item=candidate.row.item_name.strip(),
                        tree_level=1,
                        source_table_index=table_index,
                        grouping_mode=(
                            table_grouping_modes.get(table_index, "none")
                            if table_grouping_modes
                            else "none"
                        ),
                    )
                    insert_position = len(working_items)
                    for position, existing_item in enumerate(working_items):
                        if item_table_index(existing_item) != table_index:
                            continue
                        existing_row_position = source_position(existing_item, table_rows)
                        if (
                            existing_row_position is not None
                            and existing_row_position >= candidate.row.row_index
                        ):
                            insert_position = position
                            break
                    working_items.insert(insert_position, parent_item)
                    if item_table_indexes is not None:
                        item_table_indexes[id(parent_item)] = table_index
                    recovered_parent_count += 1

                # 新补回的节点已按结构父项初始化；模型原本返回的父项保留既有真实 BOM 关系。
                candidate_nodes.append((candidate, parent_item))

        for candidate, parent_item in candidate_nodes:
            for child_row in candidate.child_rows:
                child_item = find_matching_item(
                    child_row,
                    candidate.table_index,
                    allow_specification_name=candidate.candidate_type == "rowspan",
                    exclude_item=parent_item,
                )
                if child_item is None or child_item is parent_item:
                    continue
                child_item.parent_item = parent_item.item_name.strip()
                child_item.root_item = parent_item.root_item or parent_item.item_name.strip()
                child_item.tree_level = (parent_item.tree_level or 1) + 1
                child_item.per_set_quantity = None
                bound_child_count += 1

        # 旧修复可能已经把外层分组插到模型明细末尾；恢复后按源表首行位置重新排列，
        # 保证“其他 → 电缆父项 → 电缆规格”和“光伏发电设备 → 组件/逆变器”的展示顺序稳定。
        candidate_node_ids = {id(parent_item) for _, parent_item in candidate_nodes}
        for table_rows in source_tables:
            table_index = table_rows[0].table_index if table_rows else None
            if table_index is None:
                continue
            table_items_with_positions = [
                (position, item)
                for position, item in enumerate(working_items)
                if item_table_index(item) == table_index
            ]
            if len(table_items_with_positions) <= 1:
                continue
            sorted_table_items = sorted(
                table_items_with_positions,
                key=lambda pair: (
                    source_position(pair[1], table_rows) is None,
                    source_position(pair[1], table_rows)
                    if source_position(pair[1], table_rows) is not None
                    else len(table_rows) + pair[0],
                    0 if id(pair[1]) in candidate_node_ids else 1,
                    pair[0],
                ),
            )
            for (target_position, _), (_, sorted_item) in zip(
                table_items_with_positions,
                sorted_table_items,
            ):
                working_items[target_position] = sorted_item

        if recovered_parent_count or bound_child_count:
            logger.info(
                "[EngineeringService] 按源表恢复遗漏结构父项：补回=%d，绑定子项=%d，限定表格=%d",
                recovered_parent_count,
                bound_child_count,
                len(allowed_table_indexes) if allowed_table_indexes is not None else 0,
            )
        if skipped_explicit_candidate_count:
            logger.info(
                "[EngineeringService] 已跳过明确 BOM 分支的旧结构恢复候选：数量=%d",
                skipped_explicit_candidate_count,
            )
        return working_items

    @staticmethod
    def _restore_missing_explicit_bom_rows_from_source(
        items: list[EquipmentItem],
        source_context: str,
        item_table_indexes: Optional[dict[int, int]] = None,
        allowed_table_indexes: Optional[set[int]] = None,
        table_grouping_modes: Optional[dict[int, GroupingMode]] = None,
    ) -> list[EquipmentItem]:
        """依据“每套包含”等明确证据恢复模型漏提的 BOM 组成行。"""
        if not items or not source_context:
            return items

        source_tables = _source_rows_from_context(source_context)
        raw_tables = _extract_ordered_structural_tables(source_context)
        if not source_tables or not raw_tables:
            logger.debug("[EngineeringService] 无源表行可用于明确 BOM 组成恢复。")
            return items
        if item_table_indexes is None:
            assignments, _ = _assign_items_to_source_tables(items, source_tables)
            item_table_indexes = {
                id(items[item_index]): table_index
                for item_index, table_index in assignments.items()
            }

        source_table_aliases = _resolve_source_table_index_aliases(
            items, source_tables
        )
        for item in items:
            mapped_table_index = item_table_indexes.get(id(item))
            if mapped_table_index in source_table_aliases:
                item_table_indexes[id(item)] = source_table_aliases[mapped_table_index]
        effective_allowed_table_indexes = (
            {
                source_table_aliases.get(table_index, table_index)
                for table_index in allowed_table_indexes
            }
            if allowed_table_indexes is not None
            else None
        )

        working_items = list(items)
        # 记录模型原始顺序；同名同编码的设备必须依据其所在父分支匹配，不能只取全表首个候选。
        original_item_positions = {
            id(item): position for position, item in enumerate(working_items)
        }
        source_positions: dict[int, int] = {}
        composition_parent_codes: dict[int, str] = {}
        inherited_component_ids: set[int] = set()
        restored_root_count = 0
        restored_child_count = 0
        bound_count = 0

        def item_key(value: Optional[str]) -> str:
            """统一模型字段和源表字段的匹配格式。"""
            return _normalize_source_cell(value)

        def item_table_index(item: EquipmentItem) -> Optional[int]:
            """读取后处理维护的表格归属。"""
            if item_table_indexes is not None and id(item) in item_table_indexes:
                return item_table_indexes[id(item)]
            return item.source_table_index

        def find_matching_item(
            source_row: _SourceTableRow,
            table_index: int,
            excluded_ids: Optional[set[int]] = None,
            position_range: Optional[tuple[int, int]] = None,
            allow_code_mismatch: bool = False,
        ) -> Optional[EquipmentItem]:
            """按当前表格及父分支区间寻找模型项，避免同名设备跨分支串联。"""
            source_code = item_key(source_row.item_code)
            source_name = item_key(
                _normalize_source_bom_parent_name(source_row.item_name)
            )
            source_specification = item_key(source_row.specifications)
            source_unit = item_key(source_row.unit)
            candidates: list[tuple[int, int, EquipmentItem]] = []
            for position, item in enumerate(working_items):
                if excluded_ids and id(item) in excluded_ids:
                    continue
                if item_table_index(item) != table_index:
                    continue
                model_name = item_key(
                    _normalize_source_bom_parent_name(item.item_name)
                )
                if model_name != source_name:
                    continue
                model_code = item_key(item.item_code)
                if (
                    not allow_code_mismatch
                    and model_code
                    and source_code
                    and model_code != source_code
                ):
                    continue
                original_position = original_item_positions.get(id(item))
                if (
                    position_range is not None
                    and original_position is not None
                    and not position_range[0] <= original_position <= position_range[1]
                ):
                    # 有父分支边界时，宁可按源表补建，也不能把另一箱变的同名项挪过来。
                    continue
                score = 30
                if model_code and source_code and model_code == source_code:
                    score += 20
                if source_specification and item_key(item.specifications) == source_specification:
                    score += 8
                if source_unit and item_key(item.unit) == source_unit:
                    score += 3
                if source_row.quantity is not None and item.quantity == source_row.quantity:
                    score += 2
                if position_range is not None and original_position is not None:
                    score += 40
                candidates.append((score, -position, item))
            if not candidates:
                return None
            return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]

        def normalize_source_row_name(source_row: _SourceTableRow) -> _SourceTableRow:
            """清理成套提示后的父项名称，保持源表行号和计量字段不变。"""
            normalized_name = _normalize_source_bom_parent_name(source_row.item_name)
            if normalized_name == source_row.item_name.strip():
                return source_row
            return _SourceTableRow(
                table_index=source_row.table_index,
                row_index=source_row.row_index,
                item_code=source_row.item_code,
                item_name=normalized_name,
                specifications=source_row.specifications,
                unit=source_row.unit,
                quantity=source_row.quantity,
            )

        def build_explicit_branch_rows(
            table_rows: list[_SourceTableRow],
            start_index: int,
            end_index: int,
        ) -> list[_SourceTableRow]:
            """把 rowspan 父行及其连续规格恢复为父项和组成子项。"""
            branch_rows: list[_SourceTableRow] = []
            index = start_index
            while index < end_index:
                current_row = table_rows[index]
                group_end = index + 1
                while group_end < end_index:
                    next_row = table_rows[group_end]
                    if (
                        item_key(next_row.item_code) != item_key(current_row.item_code)
                        or item_key(next_row.item_name)
                        != item_key(current_row.item_name)
                    ):
                        break
                    group_end += 1

                group_rows = table_rows[index:group_end]
                parent_row = normalize_source_row_name(group_rows[0])
                branch_rows.append(parent_row)
                has_composition_suffix = (
                    _normalize_source_bom_parent_name(group_rows[0].item_name)
                    != group_rows[0].item_name.strip()
                )
                if has_composition_suffix and len(group_rows) >= 2:
                    # 同一个 rowspan 父项的首行及续行规格共同组成一个解析上下文，
                    # 避免“名称:”与后续型号、参数行因分开调用而丢失待归并状态。
                    combined_specifications = ";".join(
                        row.specifications.strip()
                        for row in group_rows
                        if row.specifications and row.specifications.strip()
                    )
                    parsed_components = _parse_source_composition_components(
                        combined_specifications
                    )
                    component_index = 0
                    for (
                        component_name,
                        component_specification,
                        component_quantity,
                        component_unit,
                    ) in parsed_components:
                        # 首个组成项沿用父项首行的计量字段，其余项只使用自身明确解析出的数量和单位。
                        first_source_row = group_rows[0]
                        inherited_quantity = (
                            component_index == 0
                            and component_quantity is None
                            and first_source_row.quantity is not None
                            and bool(first_source_row.unit)
                        )
                        component_row = _SourceTableRow(
                            table_index=first_source_row.table_index,
                            row_index=first_source_row.row_index,
                            item_code=first_source_row.item_code,
                            item_name=component_name,
                            specifications=component_specification,
                            unit=first_source_row.unit if inherited_quantity else component_unit,
                            quantity=(
                                first_source_row.quantity
                                if inherited_quantity
                                else component_quantity
                            ),
                        )
                        branch_rows.append(component_row)
                        composition_parent_codes[id(component_row)] = item_key(
                            parent_row.item_code
                        )
                        if inherited_quantity:
                            inherited_component_ids.add(id(component_row))
                        component_index += 1
                index = group_end
            return branch_rows

        def get_branch_position_range(
            marker_index: int,
            marker_positions: list[int],
        ) -> Optional[tuple[int, int]]:
            """根据模型原始顺序计算当前括号分组的候选位置范围。"""
            marker_row = table_rows[marker_index]
            marker_item = find_matching_item(marker_row, table_index)
            marker_position = (
                original_item_positions.get(id(marker_item))
                if marker_item is not None
                else None
            )
            previous_position: Optional[int] = None
            if marker_index != marker_positions[0]:
                previous_row = table_rows[
                    marker_positions[marker_positions.index(marker_index) - 1]
                ]
                previous_item = find_matching_item(previous_row, table_index)
                previous_position = (
                    original_item_positions.get(id(previous_item))
                    if previous_item is not None
                    else None
                )
            next_position: Optional[int] = None
            marker_offset = marker_positions.index(marker_index)
            if marker_offset + 1 < len(marker_positions):
                next_row = table_rows[marker_positions[marker_offset + 1]]
                next_item = find_matching_item(next_row, table_index)
                next_position = (
                    original_item_positions.get(id(next_item))
                    if next_item is not None
                    else None
                )
            if marker_position is None and next_position is None and previous_position is None:
                return None
            start_position = (
                marker_position
                if marker_position is not None
                else (previous_position + 1 if previous_position is not None else 0)
            )
            end_position = (
                next_position - 1
                if next_position is not None and next_position > start_position
                else len(original_item_positions)
            )
            return start_position, end_position

        def source_position(item: EquipmentItem, table_rows: list[_SourceTableRow]) -> Optional[int]:
            """定位模型项的原文行号，用于恢复后的稳定排序。"""
            known_position = source_positions.get(id(item))
            if known_position is not None:
                return known_position
            model_code = item_key(item.item_code)
            model_name = item_key(item.item_name)
            model_specification = item_key(item.specifications)
            positions = [
                row.row_index
                for row in table_rows
                if (not model_code or item_key(row.item_code) == model_code)
                and model_name in {
                    item_key(row.item_name),
                    item_key(row.specifications),
                }
                or (
                    not model_code
                    and model_specification
                    and model_specification == item_key(row.specifications)
                )
            ]
            return min(positions) if positions else None

        def fill_source_fields(
            item: EquipmentItem,
            source_row: _SourceTableRow,
            table_index: int,
            total_quantity: Optional[float],
        ) -> None:
            """用源表补齐模型遗漏字段，并以源表数量校正 BOM 总量。"""
            normalized_parent_name = _normalize_source_bom_parent_name(
                item.item_name
            )
            if normalized_parent_name != item.item_name.strip():
                # 模型可能把“每套包含”连同提示词写进父项名称；提示词不属于设备名称。
                item.item_name = normalized_parent_name
            if not item.item_code:
                item.item_code = source_row.item_code
            if not item.specifications and source_row.specifications:
                item.specifications = source_row.specifications
            if not item.unit and source_row.unit:
                item.unit = source_row.unit
            if source_row.quantity is not None and total_quantity is not None:
                item.quantity = total_quantity
            item.source_table_index = table_index
            item.grouping_mode = (
                table_grouping_modes.get(table_index, "external")
                if table_grouping_modes
                else "external"
            )
            if item_table_indexes is not None:
                item_table_indexes[id(item)] = table_index
            source_positions[id(item)] = source_row.row_index

        for table_rows in source_tables:
            if not table_rows:
                continue
            table_index = table_rows[0].table_index
            if (
                effective_allowed_table_indexes is not None
                and table_index not in effective_allowed_table_indexes
            ):
                continue
            if table_index >= len(raw_tables):
                continue

            marker_positions = [
                index
                for index, row in enumerate(table_rows)
                if _is_section_marker_code(row.item_code)
            ]
            for marker_offset, marker_index in enumerate(marker_positions):
                root_row = table_rows[marker_index]
                section_end = (
                    marker_positions[marker_offset + 1]
                    if marker_offset + 1 < len(marker_positions)
                    else len(table_rows)
                )
                has_explicit_composition = _source_has_explicit_composition(
                    raw_tables[table_index],
                    root_row.row_index,
                    table_rows[section_end].row_index
                    if section_end < len(table_rows)
                    else len(raw_tables[table_index]),
                )
                if not has_explicit_composition:
                    continue

                branch_source_rows = table_rows[marker_index + 1 : section_end]
                has_rowspan_composition_parent = any(
                    _normalize_source_bom_parent_name(row.item_name)
                    != row.item_name.strip()
                    for row in branch_source_rows
                )
                if (
                    not _source_row_has_real_measurement(root_row)
                    and not has_rowspan_composition_parent
                ):
                    # 无计量的括号行只有在本分支存在明确成套父项时才恢复。
                    continue

                branch_rows = build_explicit_branch_rows(
                    table_rows,
                    marker_index + 1,
                    section_end,
                )
                if not branch_rows:
                    continue
                branch_position_range = get_branch_position_range(
                    marker_index,
                    marker_positions,
                )
                # 必须有模型命中锚点，避免上下文中仅有源表时批量制造结果。
                evidence_rows = [root_row, *branch_rows]
                if not any(
                    find_matching_item(
                        row,
                        table_index,
                        position_range=branch_position_range,
                        allow_code_mismatch=id(row) in composition_parent_codes,
                    )
                    for row in evidence_rows
                ):
                    continue

                root_item = find_matching_item(
                    root_row,
                    table_index,
                    position_range=branch_position_range,
                )
                context_item = next(
                    (
                        item for item in working_items
                        if item_table_index(item) == table_index
                    ),
                    None,
                )
                if root_item is None:
                    root_item = EquipmentItem(
                        item_code=root_row.item_code,
                        item_name=root_row.item_name,
                        specifications=root_row.specifications,
                        quantity=root_row.quantity,
                        unit=root_row.unit,
                        section_name=(context_item.section_name if context_item else None),
                        section_evidence=(
                            context_item.section_evidence if context_item else None
                        ),
                        root_item=root_row.item_name.strip(),
                        tree_level=1,
                        source_table_index=table_index,
                        grouping_mode="external",
                    )
                    working_items.append(root_item)
                    restored_root_count += 1
                fill_source_fields(
                    root_item, root_row, table_index, root_row.quantity
                )
                root_item.parent_item = None
                root_item.root_item = root_item.item_name.strip()
                root_item.tree_level = 1
                root_item.per_set_quantity = None
                root_name = root_item.item_name.strip()
                root_quantity = root_row.quantity
                branch_nodes: dict[str, EquipmentItem] = {
                    item_key(root_row.item_code): root_item,
                }
                quantity_products: dict[str, float] = {
                    item_key(root_row.item_code): 1.0,
                }
                branch_item_ids: set[int] = {id(root_item)}

                for source_row in branch_rows:
                    source_code = item_key(source_row.item_code)
                    is_composition_component = id(source_row) in composition_parent_codes
                    if not is_composition_component and source_code in branch_nodes:
                        continue
                    parent_code = composition_parent_codes.get(id(source_row)) or (
                        source_code.rsplit(".", 1)[0]
                        if _is_dotted_hierarchy_code(source_code)
                        else item_key(root_row.item_code)
                    )
                    parent_item = branch_nodes.get(parent_code, root_item)
                    parent_product = quantity_products.get(parent_code, 1.0)
                    if (
                        is_composition_component
                        and id(source_row) in inherited_component_ids
                    ):
                        # 首个柜体/本体组成项沿用父项总量，但不是父项内部的单套定额。
                        current_product = parent_product
                        total_quantity = (
                            root_quantity * current_product
                            if root_quantity is not None
                            else current_product
                        )
                        per_set_quantity = None
                    else:
                        current_product = parent_product * (
                            source_row.quantity
                            if source_row.quantity is not None
                            else 1.0
                        )
                        total_quantity = (
                            root_quantity * current_product
                            if root_quantity is not None and source_row.quantity is not None
                            else (
                                current_product
                                if root_quantity is None and source_row.quantity is not None
                                else None
                            )
                        )
                        per_set_quantity = source_row.quantity
                        if (
                            root_quantity is None
                            and not is_composition_component
                            and not _is_dotted_hierarchy_code(source_code)
                        ):
                            # 外层括号行无总套数时，普通整数行是实际清单数量，
                            # 不是“每套”定额，避免把 2 面误写成单套配置数。
                            per_set_quantity = None
                    child_item = find_matching_item(
                        source_row,
                        table_index,
                        branch_item_ids,
                        position_range=branch_position_range,
                        allow_code_mismatch=is_composition_component,
                    )
                    if child_item is None:
                        child_item = EquipmentItem(
                            item_code=source_row.item_code,
                            item_name=source_row.item_name,
                            specifications=source_row.specifications,
                            quantity=total_quantity,
                            unit=source_row.unit,
                            section_name=root_item.section_name,
                            section_evidence=root_item.section_evidence,
                            parent_item=parent_item.item_name.strip(),
                            root_item=root_name,
                            tree_level=(parent_item.tree_level or 1) + 1,
                            per_set_quantity=per_set_quantity,
                            source_table_index=table_index,
                            grouping_mode="external",
                        )
                        working_items.append(child_item)
                        restored_child_count += 1
                    else:
                        fill_source_fields(
                            child_item, source_row, table_index, total_quantity
                        )
                    child_item.parent_item = parent_item.item_name.strip()
                    child_item.root_item = root_name
                    child_item.tree_level = (parent_item.tree_level or 1) + 1
                    child_item.per_set_quantity = per_set_quantity
                    if not is_composition_component:
                        branch_nodes[source_code] = child_item
                        quantity_products[source_code] = current_product
                    branch_item_ids.add(id(child_item))
                    bound_count += 1

        # 仅重排同一源表内的项目，保留不同表格之间的边界和原有未归属项。
        for table_rows in source_tables:
            if not table_rows:
                continue
            table_index = table_rows[0].table_index
            table_slots = [
                position for position, item in enumerate(working_items)
                if item_table_index(item) == table_index
            ]
            if len(table_slots) <= 1:
                continue
            table_items = [working_items[position] for position in table_slots]
            table_items.sort(
                key=lambda item: (
                    source_position(item, table_rows) is None,
                    source_position(item, table_rows)
                    if source_position(item, table_rows) is not None
                    else len(table_rows),
                )
            )
            for position, item in zip(table_slots, table_items):
                working_items[position] = item

        if restored_root_count or restored_child_count or bound_count:
            logger.info(
                "[EngineeringService] 按明确 BOM 组成证据恢复源表行：补回父项=%d，补回组成=%d，绑定关系=%d",
                restored_root_count,
                restored_child_count,
                bound_count,
            )
        return working_items


