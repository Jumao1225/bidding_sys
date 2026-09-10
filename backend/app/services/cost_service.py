"""
BOM 成本核算与层级树聚合服务模块 (Cost Service)
提供多级嵌套 BOM 成本分项的自底向上（Bottom-Up）层级金额汇总、折算单价计算与项目预估总成本防双重计费统计。
"""
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Tuple
from loguru import logger


def _read_cost_item_field(item: Any, field_name: str) -> Any:
    """兼容读取字典和 ORM 成本明细对象的字段。"""
    if isinstance(item, Mapping):
        return item.get(field_name)
    return getattr(item, field_name, None)


def is_root_cost_item(item: Any) -> bool:
    """判断成本明细是否为 BOM 顶层节点，避免父子节点重复计费。"""
    parent_node_id = str(_read_cost_item_field(item, "parent_node_id") or "").strip()
    if parent_node_id:
        return False

    parent_item = str(_read_cost_item_field(item, "parent_item") or "").strip()
    if not parent_item:
        return True

    raw_tree_level = _read_cost_item_field(item, "tree_level")
    if raw_tree_level is None or str(raw_tree_level).strip() == "":
        return False

    try:
        return Decimal(str(raw_tree_level)) == Decimal("1")
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("BOM 成本明细层级格式异常，按非顶层节点处理：{}", raw_tree_level)
        return False


def sum_root_cost_items(items: Iterable[Any]) -> float:
    """仅汇总 BOM 顶层节点金额，兼容成本字典和 CostEstimate ORM 对象。"""
    total = Decimal("0.00")
    item_count = 0
    root_count = 0

    for item in items or []:
        item_count += 1
        if not is_root_cost_item(item):
            continue

        root_count += 1
        raw_total = _read_cost_item_field(item, "calculated_total")
        if raw_total is None or raw_total == "":
            raw_total = _read_cost_item_field(item, "subtotal")
        if raw_total is None or raw_total == "":
            continue

        try:
            amount = Decimal(str(raw_total))
            if amount.is_finite():
                total += amount
        except (InvalidOperation, TypeError, ValueError):
            logger.warning("BOM 顶层节点金额格式异常，已跳过：{}", raw_total)

    normalized_total = total.quantize(Decimal("0.01"))
    logger.debug(
        "BOM 顶层金额汇总完成：明细 {} 条，顶层 {} 条，总额 {}",
        item_count,
        root_count,
        normalized_total,
    )
    return float(normalized_total)


def resolve_cost_total(
    cost_analysis: Mapping[str, Any] | None = None,
    cost_items: Iterable[Any] | None = None,
) -> float:
    """优先读取标准成本总额，历史数据再按顶层节点金额兜底计算。"""
    raw_total = cost_analysis.get("total_cost") if isinstance(cost_analysis, Mapping) else None
    if raw_total is not None and str(raw_total).strip() != "":
        try:
            amount = Decimal(str(raw_total))
            if amount.is_finite() and amount >= 0:
                return float(amount.quantize(Decimal("0.01")))
        except (InvalidOperation, TypeError, ValueError):
            logger.warning("成本分析总额格式异常，改用顶层 BOM 节点兜底：{}", raw_total)

    fallback_total = sum_root_cost_items(cost_items or [])
    logger.warning("成本分析缺少有效标准总额，已按顶层 BOM 节点兜底汇总：{}", fallback_total)
    return fallback_total


def is_cost_price_unset(value: Any) -> bool:
    """判断成本单价是否为空或未形成有效报价。"""
    if value is None or value == "":
        return True

    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        logger.warning("成本单价格式异常，按未定价处理：{}", value)
        return True


def rollup_hierarchical_cost_items(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float, int]:
    """
    对多级 BOM 成本分项列表执行自底向上（Bottom-Up）层级金额汇总：
    1. 若父节点（成套主标的物/总成分项）自身未指定独立打包单价（ref_price <= 0 或为成套汇总/未匹配），且子项有计算金额，
       则自动将所有直接子节点 subtotal 累加为父节点 subtotal，并折算父节点单价 ref_price = subtotal / qty，
       置信度自动标记 match_quality = '成套汇总'；
    2. 若父节点自身已具备明确的成套打包统价，则保持父节点自身统价；
    3. 项目预估总成本 total_cost 严格基于所有顶层根节点（Level 1 或 parent_item 为空）的 subtotal 进行求和，
       彻底杜绝父节点与子节点双重计费（Double-Counting）；
    4. 返回三元组：(processed_items, total_cost, unmatched_count)。
    """
    if not items:
        return [], 0.0, 0

    # 1. 建立节点与父子关系映射（支持同名但不同上下文的回溯就近挂载）
    nodes = []
    for idx, item in enumerate(items):
        raw_qty = item.get("qty")
        try:
            qty = float(raw_qty) if raw_qty is not None else 1.0
        except (ValueError, TypeError):
            qty = 1.0
            
        raw_price = item.get("ref_price")
        try:
            price = float(raw_price) if raw_price is not None else 0.0
        except (ValueError, TypeError):
            price = 0.0

        subtotal = round(qty * price, 2)
        node = dict(item)
        node["_orig_idx"] = idx
        node["qty"] = qty
        node["ref_price"] = price
        node["subtotal"] = subtotal
        node["_children"] = []
        node["_parent"] = None
        nodes.append(node)

    # 2. 挂载父子树：优先使用稳定节点 ID，历史数据再使用名称回溯兼容。
    root_nodes = []

    node_by_id = {
        str(node.get("node_id")).strip(): node
        for node in nodes
        if str(node.get("node_id") or "").strip()
    }

    def _same_source_table(current: dict, candidate: dict) -> bool:
        """按分组模式判断父子项是否处于同一层级作用域。

        表格外分区模式下，PDF 分页可能把一张清单拆成多个物理表格片段；
        同一外部分区内应允许跨片段恢复 BOM 父子关系。其它模式继续使用
        来源表格索引隔离，避免重复编号的不同清单相互串挂。
        """
        current_mode = current.get("grouping_mode")
        candidate_mode = candidate.get("grouping_mode")
        if current_mode == "external" and candidate_mode == "external":
            current_section = str(current.get("section_name") or "").strip()
            candidate_section = str(candidate.get("section_name") or "").strip()
            return (
                not current_section
                or not candidate_section
                or current_section == candidate_section
            )

        current_table = current.get("source_table_index")
        candidate_table = candidate.get("source_table_index")
        return (
            current_table is None
            or candidate_table is None
            or current_table == candidate_table
        )

    for i, node in enumerate(nodes):
        parent_node_id = str(node.get("parent_node_id") or "").strip()
        if parent_node_id:
            found_parent = node_by_id.get(parent_node_id)
            if found_parent is not None and found_parent is not node:
                # 稳定 ID 是人工维护层级的最终证据，人工调整允许跨来源表建立明确的父子关系。
                node["parent_item"] = found_parent.get("name")
                found_parent["_children"].append(node)
                node["_parent"] = found_parent
                logger.debug(
                    "BOM 使用稳定父节点关系：{} -> {}",
                    node.get("node_id"),
                    found_parent.get("node_id"),
                )
                continue

        parent_name = str(node.get("parent_item") or "").strip()
        if parent_name:
            exact_parent = None
            partial_parent = None
            for j in range(i - 1, -1, -1):
                prev = nodes[j]
                prev_name = str(prev.get("name") or "").strip()
                
                # 名称回退先记录精确匹配，避免短父名（如“光伏”）被复合设备名抢先匹配。
                exact_name_match = prev_name == parent_name
                partial_name_match = bool(parent_name and parent_name in prev_name)
                node_root = str(node.get("root_item") or "").strip()
                prev_root = str(prev.get("root_item") or "").strip()
                root_match = not node_root or not prev_root or (node_root == prev_root) or (node_root == prev_name) or (node_root in prev_name)
                if not root_match or not _same_source_table(node, prev) or prev is node:
                    continue
                if exact_name_match and exact_parent is None:
                    exact_parent = prev
                elif partial_name_match and partial_parent is None:
                    partial_parent = prev
            found_parent = exact_parent or partial_parent
            if found_parent is not None:
                node["parent_node_id"] = found_parent.get("node_id") or node.get("parent_node_id")
                found_parent["_children"].append(node)
                node["_parent"] = found_parent
            else:
                root_nodes.append(node)
        else:
            root_nodes.append(node)

    # 3. 后序递归自底向上汇总金额与折算单价
    def _rollup(n: dict) -> float:
        curr_price = float(n.get("ref_price") or 0.0)
        curr_mq = n.get("match_quality")

        is_parent_modified = bool(n.get("is_parent_modified")) or n.get("pricing_mode") == "parent"

        if n["_children"]:
            children_sum = 0.0
            for child in n["_children"]:
                children_sum += _rollup(child)
            children_sum = round(children_sum, 2)

            # 若父节点已被用户直接自定义修改定价，则父项统价优先，不被子项汇总覆盖
            if is_parent_modified and curr_price > 0:
                q = n.get("qty") if (n.get("qty") and n.get("qty") > 0) else 1.0
                n["subtotal"] = round(q * curr_price, 2)
                if not n.get("match_quality") or n.get("match_quality") in ["未匹配", "成套汇总"]:
                    n["match_quality"] = "手动修改"
            # 若未手动修改父项且子项总金额大于 0，父节点由子项自底向上汇总驱动
            elif children_sum > 0:
                n["subtotal"] = children_sum
                q = n.get("qty") if (n.get("qty") and n.get("qty") > 0) else 1.0
                n["ref_price"] = round(children_sum / q, 2)
                n["match_quality"] = "成套汇总"
            elif curr_price > 0 and curr_mq not in ["未匹配", "成套汇总", None]:
                # 子项无金额，父节点自身有独立打包统价
                q = n.get("qty") if (n.get("qty") and n.get("qty") > 0) else 1.0
                n["subtotal"] = round(q * curr_price, 2)
            else:
                n["subtotal"] = 0.0
                n["ref_price"] = 0.0

            return n["subtotal"]
        else:
            q = n.get("qty") if (n.get("qty") and n.get("qty") > 0) else 1.0
            n["subtotal"] = round(q * curr_price, 2)
            return n["subtotal"]

    for r in root_nodes:
        _rollup(r)

    # 4. 自顶向下级联传递成套统价锁定状态（Parent Dominance）
    def _apply_parent_lock(node: dict, locked_by_ancestor: bool = False) -> None:
        """自顶向下标记被上级统价锁定的后代节点，并归零其独立小计。"""
        node["is_locked_by_parent"] = locked_by_ancestor
        is_parent_modified = bool(node.get("is_parent_modified")) or node.get("pricing_mode") == "parent"
        curr_price = float(node.get("ref_price") or 0.0)

        # 若已被上级锁定，小计归零，防止外部脏累加
        if locked_by_ancestor:
            node["subtotal"] = 0.0

        # 当前节点是否有子项且自身启用了成套统价
        child_locked = locked_by_ancestor or (bool(node["_children"]) and is_parent_modified and curr_price > 0)
        for child in node["_children"]:
            _apply_parent_lock(child, child_locked)

    for r in root_nodes:
        _apply_parent_lock(r, False)

    # 5. 统计预估总成本（严格以顶层根节点 subtotal 求和）与未匹配数
    total_cost = round(sum(r["subtotal"] for r in root_nodes), 2)
    unmatched_count = 0

    clean_items = []
    for node in nodes:
        node.pop("_children", None)
        node.pop("_parent", None)
        node.pop("_orig_idx", None)
        # 结构节点或已被上级成套统价锁定的节点，不应被统计为未匹配报价项
        is_structural_node = bool(node.get("is_structural")) or (
            node.get("qty") is None and not str(node.get("unit") or "").strip()
        )
        is_locked = bool(node.get("is_locked_by_parent"))
        if float(node.get("ref_price") or 0.0) <= 0 and not is_structural_node and not is_locked:
            unmatched_count += 1
            if not node.get("match_quality"):
                node["match_quality"] = "未匹配"
        clean_items.append(node)

    return clean_items, total_cost, unmatched_count


def merge_cost_analysis_with_manual_structure(
    fresh_cost_analysis: Dict[str, Any],
    saved_cost_analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """合并重新匹配结果与已保存的人工 BOM 结构。

    重新匹配只刷新自动匹配节点的价格与匹配信息；当前清单的节点集合、顺序、父子关系、
    手动新增/删除结果以及手动修改的价格字段均以已保存清单为准。
    """
    fresh_items = fresh_cost_analysis.get("items") if isinstance(fresh_cost_analysis, dict) else None
    saved_items = saved_cost_analysis.get("items") if isinstance(saved_cost_analysis, dict) else None
    if not isinstance(fresh_items, list) or not isinstance(saved_items, list) or not saved_items:
        return fresh_cost_analysis

    used_fresh_indices: set[int] = set()

    def normalized_text(item: Dict[str, Any], *fields: str) -> str:
        for field in fields:
            value = str(item.get(field) or "").strip()
            if value:
                return value
        return ""

    def find_fresh_item(saved_item: Dict[str, Any]) -> Dict[str, Any] | None:
        saved_node_id = normalized_text(saved_item, "node_id")
        if saved_node_id:
            for index, fresh_item in enumerate(fresh_items):
                if index not in used_fresh_indices and normalized_text(fresh_item, "node_id") == saved_node_id:
                    used_fresh_indices.add(index)
                    return fresh_item

        saved_code = normalized_text(saved_item, "item_code")
        saved_names = {
            normalized_text(saved_item, "name", "item_name"),
            normalized_text(saved_item, "raw_name"),
        }
        saved_names.discard("")
        for index, fresh_item in enumerate(fresh_items):
            if index in used_fresh_indices:
                continue
            fresh_code = normalized_text(fresh_item, "item_code")
            fresh_name = normalized_text(fresh_item, "name", "item_name")
            if saved_code and fresh_code == saved_code and fresh_name in saved_names:
                used_fresh_indices.add(index)
                return fresh_item

        for index, fresh_item in enumerate(fresh_items):
            if index in used_fresh_indices:
                continue
            fresh_name = normalized_text(fresh_item, "name", "item_name")
            if fresh_name in saved_names:
                used_fresh_indices.add(index)
                return fresh_item
        return None

    refreshed_fields = (
        "matched_name",
        "matched_brand",
        "matched_model",
        "matched_manufacturer",
        "ref_price",
        "match_quality",
        "warning",
        "comparison_note",
        "remark",
    )
    merged_items: List[Dict[str, Any]] = []
    refreshed_count = 0
    preserved_manual_count = 0

    for saved_item in saved_items:
        if not isinstance(saved_item, dict):
            continue
        merged_item = dict(saved_item)
        fresh_item = find_fresh_item(saved_item)
        is_custom_item = bool(saved_item.get("is_custom_added"))
        is_pending_custom_item = (
            is_custom_item
            and is_cost_price_unset(saved_item.get("ref_price"))
            and not saved_item.get("is_parent_modified")
            and saved_item.get("match_quality") != "手动修改"
        )
        # 手动新增子项默认带有 is_child_modified 标记，但该标记不等于用户已手动定价。
        # 只有未定价的手动新增项允许接受本次批量匹配结果，其余人工修改继续保留。
        is_manual_item = (
            saved_item.get("is_parent_modified")
            or saved_item.get("match_quality") == "手动修改"
            or (
                is_custom_item
                and not is_pending_custom_item
            )
            or (
                not is_custom_item
                and saved_item.get("is_child_modified")
            )
        )

        if fresh_item and not is_manual_item:
            for field in refreshed_fields:
                if field in fresh_item:
                    merged_item[field] = fresh_item[field]
            refreshed_count += 1
        else:
            preserved_manual_count += 1
        merged_items.append(merged_item)

    recalculated_items, total_cost, unmatched_count = rollup_hierarchical_cost_items(merged_items)
    merged_analysis = dict(fresh_cost_analysis)
    merged_analysis.update({
        "items": recalculated_items,
        "total_cost": total_cost,
        "unmatched_count": unmatched_count,
    })
    logger.info(
        "重新匹配保留人工 BOM 结构：当前清单 {} 项，刷新自动匹配 {} 项，保留人工项 {} 项",
        len(recalculated_items),
        refreshed_count,
        preserved_manual_count,
    )
    return merged_analysis


def persist_cost_estimate_rows(
    db: Any,
    document_id: str,
    tenant_id: str,
    user_id: str,
    project_id: str | None,
    items: List[Dict[str, Any]],
) -> None:
    """将最终合并后的 BOM 报价结果同步写入 CostEstimate 实体表。"""
    from app.db.models.ai_analysis import CostEstimate

    db.query(CostEstimate).filter(
        CostEstimate.document_id == document_id,
        CostEstimate.tenant_id == tenant_id,
    ).delete()

    def optional_float(value: Any) -> float | None:
        """将可选数字字段安全转换为浮点数。"""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    for sort_order, item in enumerate(items):
        quantity = item.get("qty") if item.get("qty") is not None else 1.0
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            quantity = 1.0

        db.add(CostEstimate(
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
            project_id=project_id,
            item_code=str(item.get("item_code") or "").strip() or None,
            item_name=str(item.get("name") or "未命名项"),
            quantity=quantity,
            unit=str(item.get("unit")) if item.get("unit") is not None else None,
            unit_price=optional_float(item.get("ref_price")) or 0.0,
            calculated_total=optional_float(item.get("subtotal")) or 0.0,
            brand=str(item.get("brand") or item.get("matched_brand") or "").strip() or None,
            model=str(item.get("model") or item.get("matched_model") or "").strip() or None,
            manufacturer=str(item.get("manufacturer") or item.get("matched_manufacturer") or "").strip() or None,
            spec=str(item.get("spec_requirement") or "").strip() or None,
            spec_requirement=str(item.get("spec_requirement") or "").strip() or None,
            matched_name=str(item.get("matched_name") or item.get("name") or "").strip() or None,
            matched_brand=str(item.get("matched_brand") or "").strip() or None,
            matched_model=str(item.get("matched_model") or "").strip() or None,
            matched_manufacturer=str(item.get("matched_manufacturer") or "").strip() or None,
            key_parameters=item.get("key_parameters") or [],
            brand_requirements=str(item.get("brand_requirements") or "").strip() or None,
            match_quality=str(item.get("match_quality") or "").strip() or None,
            warning=str(item.get("warning") or "").strip() or None,
            comparison_note=str(item.get("comparison_note") or "").strip() or None,
            parent_item=str(item.get("parent_item") or "").strip() or None,
            root_item=str(item.get("root_item") or "").strip() or None,
            tree_level=int(item.get("tree_level")) if item.get("tree_level") is not None else None,
            per_set_qty=optional_float(item.get("per_set_qty")),
            per_set_quantity=optional_float(item.get("per_set_quantity")),
            section_name=str(item.get("section_name") or "").strip() or None,
            remark=str(item.get("remark") or "").strip() or None,
            sort_order=sort_order,
        ))
    db.commit()
    logger.info(
        "已将最终合并后的 BOM 报价同步至 CostEstimate：文档ID={}，条目数={}",
        document_id,
        len(items),
    )
