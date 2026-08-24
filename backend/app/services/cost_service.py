"""
BOM 成本核算与层级树聚合服务模块 (Cost Service)
提供多级嵌套 BOM 成本分项的自底向上（Bottom-Up）层级金额汇总、折算单价计算与项目预估总成本防双重计费统计。
"""
from typing import List, Dict, Any, Tuple
from loguru import logger

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

    # 2. 挂载父子树（Backward Scope Matching 就近回溯算法）
    root_nodes = []
    for i, node in enumerate(nodes):
        parent_name = str(node.get("parent_item") or "").strip()
        if parent_name:
            found_parent = None
            for j in range(i - 1, -1, -1):
                prev = nodes[j]
                prev_name = str(prev.get("name") or "").strip()
                
                # 名称匹配：精确匹配，或候选父节点全称包含子项指定的父项名称（如 "4(九) 铁附件、电缆防火封堵" 包含 "铁附件、电缆防火封堵"）
                # 严禁 (prev_name in parent_name)，防止短名称同级兄弟项（如 "铁附件"）误匹配复合名称父项（如 "铁附件、电缆防火封堵"）
                name_match = (prev_name == parent_name) or (parent_name in prev_name)
                node_root = str(node.get("root_item") or "").strip()
                prev_root = str(prev.get("root_item") or "").strip()
                root_match = not node_root or not prev_root or (node_root == prev_root) or (node_root == prev_name) or (node_root in prev_name)
                if name_match and root_match and prev is not node:
                    found_parent = prev
                    break
            if found_parent is not None:
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

        if n["_children"]:
            children_sum = 0.0
            for child in n["_children"]:
                children_sum += _rollup(child)
            children_sum = round(children_sum, 2)

            # 若子项总金额大于 0，父节点始终由子项自底向上汇总驱动
            if children_sum > 0:
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

    # 4. 统计预估总成本（严格以顶层根节点 subtotal 求和）与未匹配数
    total_cost = round(sum(r["subtotal"] for r in root_nodes), 2)
    unmatched_count = 0

    clean_items = []
    for node in nodes:
        node.pop("_children", None)
        node.pop("_parent", None)
        node.pop("_orig_idx", None)
        if float(node.get("ref_price") or 0.0) <= 0:
            unmatched_count += 1
            if not node.get("match_quality"):
                node["match_quality"] = "未匹配"
        clean_items.append(node)

    return clean_items, total_cost, unmatched_count
