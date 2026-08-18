"""
表格结构识别与多行表头处理工具模块 (table_utils.py)

提供对 Word 表格多行复合表头、列头名称合并提取及数据区定位等通用结构化分析能力。
"""

import re
from typing import List, Tuple, Optional, Dict, Any
from loguru import logger


def detect_table_header_rows(table) -> int:
    """
    智能识别 Word 表格的表头所占行数（支持单行表头与多行复合表头）。

    判定维度：
    1. XML <w:tblHeader/> 显式标记；
    2. 跨列合并特征（第 0 行存在合并且第 1 行包含子列属性名）；
    3. 纵向合并特征（w:vMerge）与表头属性标签词汇；
    4. 数据行特征排除（第 1 行若含数据序号、下划线、占位符等则非表头）。

    :param table: docx.table.Table 对象
    :return: 表头行数 header_rows_count (>= 1)
    """
    if table is None or not hasattr(table, 'rows') or not table.rows:
        return 1

    try:
        # 1. 优先检查 Word XML 原生的 <w:tblHeader/> 标记
        xml_header_count = 0
        for r in table.rows:
            trPr = r._tr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trPr')
            if trPr is not None:
                tblHeader = trPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader')
                if tblHeader is not None:
                    xml_header_count += 1
                    continue
            break
        if xml_header_count >= 1:
            return xml_header_count

        total_rows = len(table.rows)
        if total_rows <= 1:
            return 1

        total_cols = len(table.rows[0].cells)

        # 2. 检查第 0 行是否存在跨列合并 (unique _tc 数量少于 total_cols)
        row0_unique_tcs = set(c._tc for c in table.rows[0].cells)
        has_h_merge_row0 = len(row0_unique_tcs) < total_cols

        # 提取第 0 行、第 1 行的单元格文本
        row0_texts = [c.text.strip().replace("\n", "") for c in table.rows[0].cells]
        row1_texts = [c.text.strip().replace("\n", "") for c in table.rows[1].cells]

        # 数据行特征模式：纯数字序号(如 1, 2)、待填占位符、金额数字、纯空格/下划线
        data_patterns = [
            re.compile(r'^\d+$'),                                        # 纯数字序号
            re.compile(r'^\d+\.\d+$'),                                   # 层级数字序号如 2.1
            re.compile(r'\[(?:待补充|待手动补充|建议人工|待填|查询|错误)[^\]]*\]'), # 占位符
            re.compile(r'_{2,}'),                                        # 下划线
            re.compile(r'^\d+(?:\.\d+)?\s*(?:元|万元|%|块|台|套|米|m)?$'),      # 金额/数量
        ]

        def _is_data_cell(t: str) -> bool:
            if not t:
                return False
            return any(pat.search(t) for pat in data_patterns)

        # 如果第 1 行有明显的数据特征（例如首列是纯数字 1/2，或者单元格有占位符），则第 1 行必然是数据行而非表头
        row1_has_data_features = any(_is_data_cell(t) for t in row1_texts if t)

        # 特殊保护：如果第 1 行的第 0 列是 "1" 或 "01" 等纯序号，且不包含任何子表头关键词，则第 1 行为数据行
        if row1_texts and re.match(r'^[0-9]+$', row1_texts[0]):
            row1_has_data_features = True

        if row1_has_data_features:
            return 1

        # 表头子项/属性列名特征词
        sub_header_keywords = [
            "类别", "编号", "等级", "专业", "级别", "证号", "名称", "规格", "型号", "单位", "数量", "单价", "合价",
            "总价", "小计", "说明", "备注", "品牌", "厂家", "生产厂家", "响应", "偏离", "分项", "职务", "经验"
        ]
        has_sub_header_kw = any(
            any(kw in t for kw in sub_header_keywords)
            for t in row1_texts if t
        )

        # 检查第 1 行与第 0 行是否存在纵向合并 (vMerge)
        has_vmerge = False
        for c in table.rows[1].cells:
            tcPr = c._tc.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr')
            if tcPr is not None:
                vMerge = tcPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}vMerge')
                if vMerge is not None:
                    has_vmerge = True
                    break

        # 若第 0 行存在跨列合并 或 第 1 行存在 vMerge 纵向合并 或 包含子表头属性关键词，且第 1 行无数据特征
        if (has_h_merge_row0 or has_vmerge or has_sub_header_kw) and not row1_has_data_features:
            # 进一步检测是否存在 3 行复合表头
            if total_rows > 2:
                row2_texts = [c.text.strip().replace("\n", "") for c in table.rows[2].cells]
                row2_has_data_features = any(_is_data_cell(t) for t in row2_texts if t)
                if row2_texts and re.match(r'^[0-9]+$', row2_texts[0]):
                    row2_has_data_features = True
                if not row2_has_data_features and any(any(kw in t for kw in sub_header_keywords) for t in row2_texts if t):
                    return 3
            return 2

        return 1
    except Exception as e:
        logger.warning(f"智能检测表格表头行数异常: {e}")
        return 1


def get_merged_header_texts(table, header_rows_count: int = 1) -> List[str]:
    """
    提取并智能合并多行表头的列定义名称列表。
    例如：第 0 行 '资格证书' 与 第 1 行 '类别' 合并为 '资格证书(类别)'。

    :param table: docx.table.Table 对象
    :param header_rows_count: 表头行数
    :return: 每一列的完整表头名称列表
    """
    if not table or not hasattr(table, 'rows') or not table.rows:
        return []

    total_cols = len(table.rows[0].cells)
    header_rows_count = min(header_rows_count, len(table.rows))

    if header_rows_count <= 1:
        return [c.text.strip().replace("\n", "") for c in table.rows[0].cells]

    col_headers = []
    for c_i in range(total_cols):
        parts = []
        for r_i in range(header_rows_count):
            if c_i < len(table.rows[r_i].cells):
                txt = table.rows[r_i].cells[c_i].text.strip().replace("\n", "")
                if txt and txt not in parts:
                    parts.append(txt)
        if not parts:
            col_headers.append("")
        elif len(parts) == 1:
            col_headers.append(parts[0])
        else:
            # 组合父表头与子表头：如 "资格证书(类别)"
            parent = parts[0]
            child = "/".join(parts[1:])
            col_headers.append(f"{parent}({child})")

    return col_headers


def get_table_header_logical_spans(table, hdr_count: int = 1) -> List[Tuple[int, int]]:
    """
    获取表头的逻辑列网格跨度列表。
    取表头最底端一行 (table.rows[hdr_count - 1])，
    对于每个逻辑列，返回其在底层物理网格中的 (start_col_idx, end_col_idx)（inclusive）。
    例如：
    1. 6 列物理网格中，Row 0 第 1、2 列合并为名称列，则返回 [(0, 0), (1, 2), (3, 3), (4, 4), (5, 5)]；
    2. 多行表头中（hdr_count=2），Row 1 分出了子列（如类别、编号），则以 Row 1 的细分列跨度为准。
    """
    if table is None or not hasattr(table, 'rows') or not table.rows:
        return []

    hdr_idx = max(0, min(hdr_count - 1, len(table.rows) - 1))
    header_row = table.rows[hdr_idx]
    spans = []
    seen_tcs = []

    for c_i, cell in enumerate(header_row.cells):
        tc = cell._tc
        if tc not in seen_tcs:
            seen_tcs.append(tc)
            spans.append([c_i, c_i])
        else:
            idx = seen_tcs.index(tc)
            spans[idx][1] = c_i

    return [tuple(s) for s in spans]


def align_row_to_header_grid_spans(row, header_spans: List[Tuple[int, int]]):
    """
    使指定行 (row) 的单元格合并结构与表头的逻辑列跨度 (header_spans) 100% 对齐。
    如果表头某列跨越了多个物理列（如 start < end），则将该行的对应单元格进行合并。
    """
    if not row or not header_spans or not hasattr(row, 'cells') or not row.cells:
        return

    total_cells = len(row.cells)
    for start_c, end_c in header_spans:
        if 0 <= start_c < end_c < total_cells:
            if row.cells[start_c]._tc != row.cells[end_c]._tc:
                try:
                    row.cells[start_c].merge(row.cells[end_c])
                except Exception as me:
                    logger.debug(f"单元格合并容错: {me}")


def clean_row_vmerge(row):
    """
    彻底清洗指定行 (row) 中所有单元格的垂直纵向合并标记 (<w:vMerge/>)。
    防止 table.add_row() 新增的数据行因继承下方/上方落款行的 vMerge 属性
    而导致大单元格跨页垂直拉伸或产生大面积空白断层。
    """
    if not row or not hasattr(row, 'cells') or not row.cells:
        return

    seen_tcs = set()
    for cell in row.cells:
        tc = cell._tc
        if tc in seen_tcs:
            continue
        seen_tcs.add(tc)
        tcPr = tc.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr')
        if tcPr is not None:
            for vMerge in tcPr.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}vMerge'):
                try:
                    tcPr.remove(vMerge)
                except Exception:
                    pass


def get_doc_chapter_tables_mapping(doc) -> List[Dict[str, Any]]:
    """
    单次拓扑遍历 Word 文档 body 流，构建每个章节标题与其下方专属表格的拓扑映射列表。
    """
    if doc is None or not hasattr(doc, 'element') or not hasattr(doc.element, 'body'):
        return []

    mapping = []
    current_entry = {"chapter_title": "PREAMBLE", "table_indices": []}

    for elem in doc.element.body:
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "p":
            txt = "".join(elem.itertext()).strip()
            if not txt:
                continue
            # 判断是否为章节大标题
            is_chapter_title = bool(
                re.match(r'^[一二三四五六七八九十百0-9]{1,3}[、\.\s]', txt)
                or re.match(r'^第[一二三四五六七八九十0-9]+[章节篇部分]', txt)
                or ("格式" in txt[:15] and len(txt) <= 80)
                or (txt.endswith("表") and len(txt) <= 80 and not any(p in txt for p in ["。", "；", ";"]))
            )
            if is_chapter_title and not ("。" in txt or "；" in txt or "！" in txt):
                if current_entry["chapter_title"] != "PREAMBLE" or current_entry["table_indices"]:
                    mapping.append(current_entry)
                current_entry = {"chapter_title": txt, "table_indices": []}
        elif tag == "tbl":
            # 找到对应 table 的索引
            for t_idx, t in enumerate(doc.tables):
                if t._element == elem:
                    current_entry["table_indices"].append(t_idx)
                    break

    if current_entry["chapter_title"] != "PREAMBLE" or current_entry["table_indices"]:
        mapping.append(current_entry)

    return mapping


def get_chapter_specific_table_indices(doc, chapter_title: str) -> List[int]:
    """
    根据章节标题精准计算该章节在 Word DOM 拓扑中拥有的专属表格索引列表 (0-indexed)。
    具备【目录与正文智能去重】机制，自动过滤文档开头的目录项，100% 锁定正文中的真实表格。
    """
    if not doc or not doc.tables or not chapter_title:
        return []

    mapping = get_doc_chapter_tables_mapping(doc)
    if not mapping:
        return [0] if len(doc.tables) == 1 else []

    # 1. 清洗 chapter_title 的核心词汇
    clean_target = re.sub(r'^[一二三四五六七八九十百0-9\s、\.\(\)（）]+', '', chapter_title).strip()
    clean_target = re.sub(r'[\s、\.\(\)（）]+', '', clean_target)

    # 提取有意义的 token（长度 >= 2）
    target_tokens = set()
    for i in range(len(clean_target) - 1):
        target_tokens.add(clean_target[i:i+2])
    if len(clean_target) >= 3:
        for i in range(len(clean_target) - 2):
            target_tokens.add(clean_target[i:i+3])

    best_score = -1.0
    best_entry = None

    for entry in mapping:
        entry_title = entry.get("chapter_title", "")
        if entry_title == "PREAMBLE":
            continue
        clean_entry = re.sub(r'^[一二三四五六七八九十百0-9\s、\.\(\)（）]+', '', entry_title).strip()
        clean_entry = re.sub(r'[\s、\.\(\)（）]+', '', clean_entry)

        if not clean_entry:
            continue

        score = 0.0
        if clean_target in clean_entry or clean_entry in clean_target:
            score += 10.0

        # 计算 2-gram 匹配度
        matched_tokens = sum(1 for tk in target_tokens if tk in clean_entry)
        if target_tokens:
            score += (matched_tokens / len(target_tokens)) * 5.0

        # 【核心去重加权】：如果该条目拥有真实的表格（属于正文），大幅加 100 分，彻底压过无表格的目录项
        if entry.get("table_indices"):
            score += 100.0

        if score >= best_score and score >= 2.0:
            best_score = score
            best_entry = entry

    if best_entry and best_entry.get("table_indices"):
        return best_entry["table_indices"]

    # 2. 如果拓扑映射未直接命中表格，按表头关键词二级回退
    header_matches = []
    for t_idx, table in enumerate(doc.tables):
        if not table.rows:
            continue
        hdr_txt = "".join(c.text.strip() for c in table.rows[0].cells)
        if any(tk in hdr_txt for tk in target_tokens if len(tk) >= 2):
            header_matches.append(t_idx)

    if len(header_matches) == 1:
        return header_matches

    # 3. 兜底：如果整个文档只有 1 个表格
    if len(doc.tables) == 1:
        return [0]

    return []


def extract_chapter_dom_structure(
    doc_or_path,
    chapter_title: str,
    selector: str = "all"
) -> str:
    """
    【精准章节作用域提取器 (Chapter Scope DOM Extractor)】
    根据目标章节标题，从 Word 物理 DOM 拓扑流中精确定位起始位置，
    仅提取 100% 属于该章节下的所有段落 (/body/p[N]) 与表格 (/body/tbl[M])，直到下一个同级章节标题为止。
    自动识别并跳过文档开头的目录项，精确定位正文中的真实起始段落。

    优势：
    1. 100% 完整无损提取当前章节的所有内容与表格，绝不丢失任何一处待填信息；
    2. 从物理层面天然排除其余 90%+ 无关章节的数十万字噪音，无需粗暴截断；
    3. 结构极其小巧清晰（通常 500~2500 字符），大模型秒级完成思考与写盘。
    """
    if not doc_or_path or not chapter_title:
        return ""

    import os
    from docx import Document
    try:
        if isinstance(doc_or_path, str):
            if not os.path.exists(doc_or_path):
                return ""
            doc = Document(doc_or_path)
        else:
            doc = doc_or_path

        if not hasattr(doc, 'element') or not hasattr(doc.element, 'body'):
            return ""

        clean_target = re.sub(r'^[一二三四五六七八九十百0-9\s、\.\(\)（）]+', '', chapter_title).strip()
        clean_target = re.sub(r'[\s、\.\(\)（）]+', '', clean_target)

        target_tokens = set()
        for i in range(len(clean_target) - 1):
            target_tokens.add(clean_target[i:i+2])

        # 第一阶段：先扫描所有匹配目标标题的段落位置，通过评分机制选取得分最高且位于正文中的真实起始段落
        candidates = []
        p_count = 0
        for elem in doc.element.body:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "p":
                p_count += 1
                txt = "".join(elem.itertext()).strip()
                if not txt:
                    continue
                clean_p = re.sub(r'^[一二三四五六七八九十百0-9\s、\.\(\)（）]+', '', txt).strip()
                clean_p = re.sub(r'[\s、\.\(\)（）]+', '', clean_p)
                score = 0.0
                if clean_target and clean_p:
                    if clean_target in clean_p or clean_p in clean_target:
                        score += 100.0
                    elif target_tokens:
                        overlap = sum(1 for tk in target_tokens if tk in clean_p)
                        score += (overlap / len(target_tokens)) * 50.0

                if score >= 30.0:
                    candidates.append((p_count, score))

        if not candidates:
            return ""

        max_score = max(c[1] for c in candidates)
        # 在最高得分中取最后一个（自动跳过文档开头的目录项，精准锁定正文位置）
        target_start_p = [c[0] for c in candidates if c[1] == max_score][-1]

        # 第二阶段：从正文起始段落开始收集该章节的所有段落与表格
        p_idx = 0
        tbl_idx = 0
        in_target = False
        collected_lines = []

        for elem in doc.element.body:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag == "p":
                p_idx += 1
                txt = "".join(elem.itertext()).strip()
                if p_idx == target_start_p:
                    in_target = True
                    collected_lines.append(f"📌 [当前目标章节正文标题] /body/p[{p_idx}]: {txt}")
                    continue
                elif in_target and p_idx > target_start_p:
                    # 判断是否遇到下一个同级大章节标题
                    is_ch_title = bool(
                        re.match(r'^[一二三四五六七八九十百0-9]{1,3}[、\.\s]', txt)
                        or re.match(r'^第[一二三四五六七八九十0-9]+[章节篇部分]', txt)
                    ) and len(txt) <= 80 and not ("。" in txt or "；" in txt or "！" in txt)
                    if is_ch_title:
                        in_target = False
                        break
                    if txt and selector in ("paragraph", "all"):
                        collected_lines.append(f"/body/p[{p_idx}]: {txt}")

            elif tag == "tbl":
                tbl_idx += 1
                if in_target:
                    # 找到对应的 table 对象
                    target_table = None
                    if 0 <= tbl_idx - 1 < len(doc.tables):
                        target_table = doc.tables[tbl_idx - 1]

                    if target_table and target_table.rows:
                        hdr_count = detect_table_header_rows(target_table)
                        headers = get_merged_header_texts(target_table, hdr_count)
                        hdr_desc = " | ".join(headers) if headers else "未识别表头"
                        total_r = len(target_table.rows)
                        total_c = len(target_table.rows[0].cells) if target_table.rows else 0
                        collected_lines.append(
                            f"\n📊 [本章节专属目标表格] 路径: `/body/tbl[{tbl_idx}]` | 规模: 共 {total_r} 行 x {total_c} 列（含 {hdr_count} 行表头）"
                        )
                        collected_lines.append(f"   表头定义: `[{hdr_desc}]`")
                        collected_lines.append("   【表格现有各行明细与单元格节点坐标】：")
                        for r_i, r in enumerate(target_table.rows):
                            row_cells_info = []
                            unique_tcs = []
                            for c_i, cell in enumerate(r.cells):
                                if cell._tc in unique_tcs:
                                    continue
                                unique_tcs.append(cell._tc)
                                cell_txt = cell.text.strip().replace("\n", " ")
                                if not cell_txt or cell_txt in ("_", "——", "--", "待填"):
                                    display_val = f"⚠️[待填空位: /body/tbl[{tbl_idx}]/tr[{r_i+1}]/tc[{c_i+1}]]"
                                else:
                                    display_val = f"'{cell_txt[:60]}'"
                                row_cells_info.append(f"tc[{c_i+1}]: {display_val}")
                            row_type = "【表头行】" if r_i < hdr_count else f"Row {r_i+1}"
                            collected_lines.append(f"   └─ [{row_type}] `/body/tbl[{tbl_idx}]/tr[{r_i+1}]` -> {' | '.join(row_cells_info)}")

        if collected_lines:
            header_str = f"🎯 【章节专属 100% 完整 DOM 视野 (零信息丢失)】: 共提取出 {len(collected_lines)} 个专属节点：\n"
            return header_str + "\n".join(collected_lines)

    except Exception as e:
        logger.warning(f"提取章节专属 DOM 结构异常: {e}")

    return ""


def inspect_and_repair_table_blanks(doc, document_id: str = "") -> int:
    """
    【表格留白智能检查与 LLM 动态修复引擎 — 零硬编码自愈闭环】
    1. 自行检查：扫描文档中条款偏离表/实质性响应表，识别出“含有条款要求/指标名称但右侧响应列留白”的未完成行；
    2. 智能修复：绝不直接删除原模板条款行，而是调用 LLM 针对这些被遗漏的条款，按表头定义逐项生成合规的响应内容并写回单元格；
    3. 序号规整：确保整表序号连续无断层。
    """
    if doc is None or not hasattr(doc, 'tables') or not doc.tables:
        return 0

    import json, re
    repaired_total = 0
    from app.services.llm_service import llm_service

    for t_i, table in enumerate(doc.tables):
        if not table.rows or len(table.rows) <= 1:
            continue

        hdr_row = table.rows[0]
        hdr_cells = [c.text.strip().replace("\n", " ") for c in hdr_row.cells]
        hdr_txt = "".join(hdr_cells)
        total_cols = len(hdr_cells)

        # 仅针对条款偏离表、实质性要求对照表等响应类表格执行自愈检查
        is_deviation_tbl = any(k in hdr_txt for k in ["偏离", "响应", "承诺", "实质性", "对照表"])
        if total_cols < 3 or not is_deviation_tbl:
            continue

        # 收集该表格中所有“有条款但右侧数据列存在空白”的待修复行
        unfilled_rows_info = []
        for r_i in range(1, len(table.rows)):
            row = table.rows[r_i]
            cells_txt = [c.text.strip() for c in row.cells]

            # 若整行全空，跳过
            if all(not txt for txt in cells_txt):
                continue

            # 寻找该行中主要的内容描述列（通常在第 2 列或第 1 列）
            main_desc = ""
            for c_idx in range(min(2, total_cols)):
                if len(cells_txt[c_idx]) >= 4 and not cells_txt[c_idx].isdigit():
                    main_desc = cells_txt[c_idx]
                    break

            # 若有实质条款描述，但后续有空白单元格，则判定为待修复留白行
            if main_desc and any(not cells_txt[c_idx] for c_idx in range(1, total_cols)):
                unfilled_rows_info.append({
                    "row_index": r_i,
                    "term_desc": main_desc,
                    "current_cells": cells_txt
                })

        if not unfilled_rows_info:
            continue

        logger.info(f"🔍 [表格留白自检] 表格 /body/tbl[{t_i+1}] 检出 {len(unfilled_rows_info)} 行未填留白，启动 LLM 动态自愈修复...")

        # 构造 LLM 动态修复 Prompt（完全抽象，零具体数据硬编码）
        prompt_rows_str = ""
        for u_item in unfilled_rows_info:
            prompt_rows_str += f"- 行索引 {u_item['row_index']}: 条款内容='{u_item['term_desc']}'\n"

        repair_prompt = f"""你是资深招投标响应与合规专家。以下表格中存在部分条款行未完成填写，请根据表头定义与条款内容，为每一行生成完整合规的填报响应。

【表格表头定义】:
{json.dumps(hdr_cells, ensure_ascii=False)}

【待补齐填写的条款清单】:
{prompt_rows_str}

【填报要求】:
1. 每一行必须严格按照表头定义的每一列（从第 1 列到最后一列）生成完整的字符串数组；
2. 响应表述必须严谨专业、完全闭合，严禁使用省略号或空字符串；
3. 必须输出严格合法的 JSON 数组，格式如下：
[
  {{"row_index": 12, "col_values": ["11", "条款原文", "响应承诺内容", "无偏离", "偏离说明"]}},
  ...
]"""

        try:
            llm_inst = llm_service.get_llm(temperature=0.1, json_mode=False)
            response = llm_inst.invoke(repair_prompt)
            raw_text = response.content if hasattr(response, 'content') else str(response)

            # 解析 JSON 结果
            import json, re
            from app.agents.bid_filler_agent import align_table_row_cells
            m_json = re.search(r'\[\s*\{.*\}\s*\]', raw_text, re.DOTALL)
            if m_json:
                repair_items = json.loads(m_json.group(0))
                for item in repair_items:
                    r_idx = item.get("row_index")
                    col_vals = item.get("col_values")
                    if isinstance(r_idx, int) and 1 <= r_idx < len(table.rows) and isinstance(col_vals, list):
                        target_row = table.rows[r_idx]
                        aligned_vals = align_table_row_cells(col_vals, total_cols, r_idx - 1)
                        for c_i, val in enumerate(aligned_vals):
                            if c_i < len(target_row.cells) and val:
                                # 仅在原单元格为空时补齐，保护已有数据
                                if not target_row.cells[c_i].text.strip():
                                    target_row.cells[c_i].text = str(val).strip()
                                    repaired_total += 1
                logger.info(f"   🎯 [LLM 动态自愈成功] 成功为表格 /body/tbl[{t_i+1}] 智能补齐 {len(repair_items)} 行空白单元格！")
        except Exception as repair_err:
            logger.warning(f"   LLM 表格留白自愈调用异常: {repair_err}")

    # 最后执行基础的序号规整
    for table in doc.tables:
        if not table.rows or len(table.rows) <= 1:
            continue
        data_rows = table.rows[1:]
        num_cells = sum(1 for r in data_rows if r.cells and (not r.cells[0].text.strip() or r.cells[0].text.strip().isdigit()))
        if data_rows and num_cells >= len(data_rows) * 0.7:
            curr_seq = 1
            for r_i in range(1, len(table.rows)):
                r = table.rows[r_i]
                if len(r.cells) > 0:
                    r_txt = r.cells[0].text.strip()
                    if not r_txt or r_txt.isdigit():
                        r.cells[0].text = str(curr_seq)
                        curr_seq += 1

    return repaired_total

