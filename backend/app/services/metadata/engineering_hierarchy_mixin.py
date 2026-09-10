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
    _EngineeringTableParser,
    _hierarchy_code_depth,
    _is_dotted_hierarchy_code,
    _is_internal_group_row,
    _is_section_marker_code,
    _normalize_source_cell,
    _should_carry_internal_group_state,
)
from .engineering_helpers import *  # noqa: F401,F403，复用工程清单通用辅助函数
from .engineering_models import EquipmentItem

logger = logging.getLogger(__name__)

class EngineeringHierarchyMixin:
    @staticmethod
    def _normalize_model_boq_group_context(
        items: list[EquipmentItem],
        source_context: str,
        allowed_table_indexes: Optional[set[int]] = None,
    ) -> list[EquipmentItem]:
        """清理模型误建的 BOQ 分类父子关系，并把分类路径回写到明细行。

        ``allowed_table_indexes`` 用于把该清理限定在表内分组模式的原始表格，
        防止外部分区表中的真实 BOM 父子关系被分类规则改写。
        """
        if not items or not source_context:
            return items

        parser = _EngineeringTableParser()
        parser.feed(source_context)
        if not parser.tables:
            return items

        context_by_code_name: dict[tuple[str, str], tuple[Optional[str], list[str]]] = {}
        context_by_name: dict[str, list[tuple[Optional[str], list[str]]]] = {}
        boq_group_names: set[str] = set()

        carried_group_state: list[tuple[str, str]] = []
        for table_index, rows in enumerate(parser.tables):
            if allowed_table_indexes is not None and table_index not in allowed_table_indexes:
                continue
            if not rows:
                continue
            if carried_group_state and not _should_carry_internal_group_state(
                "<table>"
                + "".join(
                    "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                    for row in rows
                )
                + "</table>",
                carried_group_state,
            ):
                carried_group_state = []
            candidates = {
                cells[0].strip(): cells[1].strip()
                for row_index, cells in enumerate(rows)
                if len(cells) >= 2
                and _is_internal_group_row(rows, row_index, cells[0].strip(), cells)
            }
            active_groups: dict[int, tuple[str, str]] = {
                _hierarchy_code_depth(code): (code, name)
                for code, name in carried_group_state
                if _hierarchy_code_depth(code) > 0
            }
            for row_index, cells in enumerate(rows):
                if len(cells) < 2:
                    continue
                code = cells[0].strip()
                name = cells[1].strip()
                if not name:
                    continue

                if code and code in candidates:
                    level = _hierarchy_code_depth(code)
                    if _is_section_marker_code(code):
                        active_groups = {1: (code, name)}
                    else:
                        active_groups = {
                            current_level: value
                            for current_level, value in active_groups.items()
                            if current_level < level
                        }
                        active_groups[level] = (code, name)
                    boq_group_names.add(_normalize_source_cell(name))
                    continue

                if code and _is_dotted_hierarchy_code(code):
                    level = _hierarchy_code_depth(code)
                    active_groups = {
                        current_level: value
                        for current_level, value in active_groups.items()
                        if current_level < level
                    }

                part_group = active_groups.get(1)
                context = (
                    part_group[1] if part_group else None,
                    [
                        active_groups[level][1]
                        for level in sorted(active_groups)
                        if level > 1
                    ],
                )
                normalized_code = _normalize_source_cell(code)
                normalized_name = _normalize_source_cell(name)
                if normalized_code:
                    context_by_code_name[(normalized_code, normalized_name)] = context
                context_by_name.setdefault(normalized_name, []).append(context)

            carried_group_state = [
                active_groups[level]
                for level in sorted(active_groups)
            ]

        if not boq_group_names:
            return items

        normalized_group_names = {
            _normalize_source_cell(name) for name in boq_group_names if name
        }
        model_group_names = {
            _normalize_source_cell(item.item_name)
            for item in items
            if _normalize_source_cell(item.item_name) in normalized_group_names
            and item.quantity is None
            and not str(item.unit or "").strip()
        }
        cleaned_items: list[EquipmentItem] = []
        normalized_group_node_count = 0
        cleared_parent_count = 0
        assigned_context_count = 0
        model_item_names = {
            _normalize_source_cell(item.item_name)
            for item in items
            if item.item_name
        }

        for item in items:
            normalized_name = _normalize_source_cell(item.item_name)
            normalized_parent = _normalize_source_cell(item.parent_item)
            normalized_root = _normalize_source_cell(item.root_item)
            is_boq_group_node = normalized_name in model_group_names
            should_clear_hierarchy = (
                is_boq_group_node
                or normalized_parent in normalized_group_names
                or normalized_root in normalized_group_names
            )
            if normalized_parent and normalized_parent not in model_item_names:
                # 父项名称在当前模型结果中不存在时，不能仅凭 tree_level 继续触发前端兜底挂载。
                should_clear_hierarchy = True

            if should_clear_hierarchy:
                item.parent_item = None
                item.root_item = None
                item.tree_level = 1
                item.per_set_quantity = None
                cleared_parent_count += 1
                if is_boq_group_node:
                    normalized_group_node_count += 1

            normalized_code = _normalize_source_cell(item.item_code)
            context = context_by_code_name.get((normalized_code, normalized_name))
            if context is None:
                name_contexts = context_by_name.get(normalized_name, [])
                unique_contexts = {(
                    part_name,
                    tuple(group_path),
                ) for part_name, group_path in name_contexts}
                if len(unique_contexts) == 1:
                    part_name, group_path = next(iter(unique_contexts))
                    context = (part_name, list(group_path))
            if context and not _normalize_source_cell(item.item_name) in normalized_group_names:
                part_name, group_path = context
                item.part_name = part_name
                # 原文未显式编码下级标题时，保留模型已经提取的表内路径；
                # 结构化对齐只修正顶层分部，避免为消除错误顶层分类而丢失明细归属。
                if group_path:
                    item.group_path = group_path
                assigned_context_count += 1
                if item.tree_level and item.tree_level > 1 and not item.parent_item:
                    # BOQ 分类只提供路径，不构成 BOM 父子关系；防止前端按层级再次猜父项。
                    item.tree_level = 1
                    cleared_parent_count += 1

            cleaned_items.append(item)

        if normalized_group_node_count or cleared_parent_count or assigned_context_count:
            logger.info(
                "[EngineeringService] BOQ 分类关系归一化完成：规范分类节点=%d，"
                "清理分类伪父子=%d，回写分类路径=%d",
                normalized_group_node_count,
                cleared_parent_count,
                assigned_context_count,
            )
        return cleaned_items

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
                    EngineeringHierarchyMixin._normalize_boq_hierarchy(
                        grouped_items[table_index],
                        preserve_structural_nodes=preserve_structural_nodes,
                    )
                )
            if unscoped_items:
                # 未能与原始表格对齐的异常模型项不参与跨表推断，单独按普通清单处理。
                normalized_items.extend(
                    EngineeringHierarchyMixin._normalize_boq_hierarchy(
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


