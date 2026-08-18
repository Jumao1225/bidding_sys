"""
BidFiller Worker 工厂模块 (bid_filler_workers.py)

Worker Agent 职责：读文档 → 查 DB → 产出结构化 FillProposal。
不直接写 Word —— 所有写盘由 Review Agent 审查后统一执行。
"""

import json as _json
from typing import Dict, Any, List, Optional
from loguru import logger
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage

from app.services.llm_service import llm_service
from app.agents.tools.bid_db_tools import get_all_bid_db_tools

import threading as _threading
import os
import time
import re

# 全局提案收集池（线程安全，key 为 document_id）
_PROPOSALS_LOCK = _threading.Lock()
_WORKER_PROPOSALS: Dict[str, List[Dict[str, Any]]] = {}


def get_worker_proposals(document_id: str) -> List[Dict[str, Any]]:
    """获取指定文档的所有 Worker 填写提案"""
    with _PROPOSALS_LOCK:
        return list(_WORKER_PROPOSALS.get(document_id, []))


def clear_worker_proposals(document_id: str) -> None:
    """清理指定文档的提案数据"""
    with _PROPOSALS_LOCK:
        _WORKER_PROPOSALS.pop(document_id, None)


def _filter_dom_scope(raw_structure: str, target_chapter: str, keyword: str, window_size: int = 3) -> str:
    """
    [视口切碎保持器 (Strict Scope Splicing)]
    当文档包含大量节点时，仅精准保留目标点及邻近 ±window_size 段的纯净视口，彻底消除跨章节信息过载与注意力稀释。
    硬上限约束：最多保留 25 行、总长度不超过 4000 字符，杜绝超大 DOM 导致 LLM API 超时。
    """
    if not raw_structure:
        return ""
    lines = [line.strip() for line in raw_structure.split("\n") if line.strip()]
    if len(lines) <= 30 and not keyword and len(raw_structure) <= 3500:
        return raw_structure

    search_term = keyword.strip() if keyword else target_chapter.strip()
    if not search_term:
        safe_lines = lines[:25]
        return "\n".join(safe_lines) + ("\n...(全文过长，默认仅截取前25行DOM)..." if len(lines) > 25 else "")

    matched_indices = [i for i, l in enumerate(lines) if search_term in l]
    if not matched_indices and len(search_term) > 3:
        short_term = search_term[:4]
        matched_indices = [i for i, l in enumerate(lines) if short_term in l]

    if not matched_indices:
        # 若为常规不涉及精准命中的表，回退保护不过载
        logger.info(f"   🔎 [DOM视口] 未直接命中关键词 '{search_term}'，回退截取前 3000 字符安全视口")
        return raw_structure[:3000] + ("\n...(部分跨章冗余节点已按规则保护折叠)..." if len(raw_structure) > 3000 else "")

    selected_indices = set()
    for idx in matched_indices:
        for w in range(max(0, idx - window_size), min(len(lines), idx + window_size + 1)):
            selected_indices.add(w)

    sorted_indices = sorted(selected_indices)
    filtered_lines = [lines[i] for i in sorted_indices]

    # 安全防爆 1：若匹配行数过多，仅保留前 25 行
    if len(filtered_lines) > 25:
        logger.warning(f"   ⚠️ [DOM视口保护] 匹配节点行数过多 ({len(filtered_lines)} 行)，自动修剪至前 25 行")
        filtered_lines = filtered_lines[:25] + ["...(其余冗余匹配行已自动截断以防 Token 溢出)..."]

    summary_hdr = (
        f"✂️ [切碎视口绝缘池 (Scope Spliced)]: 全文件 {len(lines)} 个 DOM 节点 -> 依据 '{search_term}' "
        f"聚合锁定前后 ±{window_size} 段 ({len(filtered_lines)} 个目标行)：\n"
    )
    result_text = summary_hdr + "\n".join(filtered_lines)

    # 安全防爆 2：硬字符上限 4000 字符
    if len(result_text) > 4000:
        logger.warning(f"   ⚠️ [DOM视口保护] 视口字符数达到 {len(result_text)} 字符，自动截断至 4000 字符")
        result_text = result_text[:4000] + "\n...(超出 4000 字符部分已安全截断)..."

    logger.info(f"   🔎 [DOM视口交付] 原始 {len(raw_structure)} 字符 -> 最终裁切交付 Agent: {len(result_text)} 字符 ({len(filtered_lines)} 行)")
    return result_text


def _build_worker_tools(docx_temp_path: str, chapter_title: str = "", collected_proposals: List[Dict[str, Any]] = None) -> List:
    """
    为 Worker 组装完整只读+直写工具集，并支持实时闭环提案捕获与安全长度守护：
    - DB 工具：全部 6 个 DB 工具；
    - Office CLI 工具：结构查询、单槽位写盘、长句原子批处理写盘、表格全量追加填充、资质图像嵌入。
    """
    if collected_proposals is None:
        collected_proposals = []

    db_tools = get_all_bid_db_tools()

    from app.agents.tools.rag_tools import get_full_chapter_text, search_bidding_document
    from app.agents.tools.office_cli_agent_tools import (
        officecli_query_structure_tool,
        officecli_write_slot_value_tool,
        officecli_batch_fill_sentence_tool,
        officecli_fill_table_rows_tool,
        officecli_add_table_row_tool,
        officecli_insert_image_tool,
    )
    import asyncio
    import concurrent.futures
    from langchain_core.tools import tool

    def _sync_call_async(async_fn, *args, **kwargs):
        """线程安全的同步调用异步函数 Helper，彻底防范 RuntimeError: no running event loop"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(async_fn(*args, **kwargs))

        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(async_fn(*args, **kwargs))).result()
        else:
            return loop.run_until_complete(async_fn(*args, **kwargs))

    @tool
    def officecli_query_structure(selector: str = "paragraph", keyword_filter: str = "", window: int = 3) -> str:
        """
        [精准切口查询工具] 查询当前 Word 文档的 DOM 结构。
        优先提供当前章节专属的 100% 完整段落与表格（零信息丢失、零跨章干扰）。
        参数：
        - selector: 'paragraph' / 'table' / 'all'
        - keyword_filter: 填入关键词短语。
        - window: 匹配点外延上下关联段数（默认 3 段）。
        """
        logger.info(f"   [Worker 视野] 查询结构 (selector='{selector}', kw='{keyword_filter}')")

        # 优先使用精准章节提取器（100% 完整无损提取当前章节专属 DOM 节点）
        from app.utils.table_utils import extract_chapter_dom_structure
        chapter_dom = extract_chapter_dom_structure(docx_temp_path, chapter_title, selector=selector)
        if chapter_dom and len(chapter_dom) > 50:
            logger.info(f"   🎯 [章节专属视野命中] 成功提取章节 [{chapter_title}] 100% 完整 DOM 结构 ({len(chapter_dom)} 字符)，零噪音且无信息丢失！")
            return chapter_dom

        # 降级：调用 OfficeCLI 并通过视口剪裁
        raw_text = _sync_call_async(officecli_query_structure_tool.coroutine, file_path=docx_temp_path, selector=selector)
        raw_str = str(raw_text)
        filtered = _filter_dom_scope(raw_str, chapter_title, keyword_filter, window)
        if selector in ("table", "all"):
            tbl_info = extract_docx_tables_summary(docx_temp_path, chapter_title)
            if tbl_info:
                return f"📊 【当前具体表格的真实表头与列定义】\n{tbl_info}\n\n{filtered}"
        return filtered

    @tool
    def officecli_write_slot_value(path: str, value: str) -> str:
        """
        [原位节点提案工具] 提议对 Word 指定节点 Path 进行 100% 格式继承的原位值替换。
        提案将自动进入主控 Agent 统一原子刷盘队列，无需在并发阶段直接修改文件。
        """
        p_path = str(path).strip()
        p_val = str(value).strip()
        logger.info(f"   [Worker 提案注册] 节点 {p_path} -> {p_val[:60]}")
        if p_path and p_val is not None:
            collected_proposals.append({
                "path": p_path,
                "proposed_text": p_val,
                "value": p_val,
                "type": "text",
                "status": "success"
            })
        return f"成功提交节点 {p_path} 的替换提案，已进入主控集中刷盘队列"
        if p_path and p_val is not None:
            collected_proposals.append({
                "path": p_path,
                "proposed_text": p_val,
                "value": p_val,
                "type": "text",
                "status": "success"
            })
        return f"成功提交节点 {p_path} 的替换提案，已进入主控集中刷盘队列"

    @tool
    def officecli_batch_fill_sentence(updates_json_str: str) -> str:
        """
        [长句/段落原子批处理提案工具] 在收集齐该章节长段落的所有字段后，一次性提交更新提案。
        参数 updates_json_str 格式：'[{{"path": "/body/p[2]", "value": "字段标签：[抽象数据内容]"}, ...]'
        """
        logger.info(f"   [Worker 原子提案注册] 提交长句批处理提案: {str(updates_json_str)[:150]}...")
        if updates_json_str:
            try:
                parsed_list = _json.loads(updates_json_str) if isinstance(updates_json_str, str) else updates_json_str
                if isinstance(parsed_list, list):
                    for it in parsed_list:
                        if isinstance(it, dict) and "path" in it:
                            val = it.get("value") or it.get("text") or it.get("proposed_text") or ""
                            collected_proposals.append({
                                "path": str(it["path"]).strip(),
                                "proposed_text": str(val).strip(),
                                "value": str(val).strip(),
                                "type": "text",
                                "status": "success"
                            })
            except Exception as je:
                logger.warning(f"   解析 updates_json_str 异常: {je}")
        return "成功提交段落批处理提案，已进入主控集中刷盘队列"

    @tool
    def officecli_fill_table_rows(table_path: str, rows_json_str: str, auto_index: bool = True) -> str:
        """
        [表格全量追加填充提案工具] 批量填充表格行，自动保留 row[1] 表头不变，并在第一列自动生成 1..N 递增序号。
        参数 rows_json_str 格式：'[["数据项1", "数据项2"], ["数据项3", "数据项4"]]'
        """
        t_path = str(table_path).strip()
        logger.info(f"   [Worker 表格提案注册] 向表格 {t_path} 提交批量填充行提案")
        val_str = rows_json_str if isinstance(rows_json_str, str) else _json.dumps(rows_json_str, ensure_ascii=False)
        if t_path and val_str:
            collected_proposals.append({
                "path": t_path,
                "proposed_text": val_str,
                "value": val_str,
                "type": "table_rows",
                "status": "success"
            })
        return f"成功提交表格 {t_path} 的数据行提案，已进入主控集中刷盘队列"

    @tool
    def officecli_insert_image(target_path: str, image_path: str, width_inches: float = 5.5, caption: str = "") -> str:
        """
        [资质证明与图片嵌入提案工具] 在 Word 指定节点 Path (如 '/body/p[12]' 或 '/body/tbl[1]/row[2]/cell[1]') 提议插入资质证明/证书图片。
        参数：
        - target_path: Word 中的物理 DOM 节点 Path
        - image_path: 资质证书图片的磁盘绝对路径 (可通过 query_company_qualification_tool 查库获取)
        - width_inches: 图片宽度 (默认 5.5 英寸)
        - caption: 图片说明图注 (可选，如 '[资质名称]')
        """
        tg_path = str(target_path).strip()
        img_path = str(image_path).strip()
        logger.info(f"   [Worker 图片提案注册] 节点 {tg_path} -> 提议嵌入图片 {img_path}")
        if tg_path and img_path:
            collected_proposals.append({
                "path": tg_path,
                "proposed_text": img_path,
                "value": img_path,
                "type": "image",
                "caption": str(caption or "").strip(),
                "status": "success"
            })
        return f"成功提交节点 {tg_path} 的资质图片嵌入提案，已进入主控集中刷盘队列"

    from app.agents.tools.style_extractor_tool import extract_text_by_style
    worker_tools = [
        officecli_query_structure,
        officecli_write_slot_value,
        officecli_batch_fill_sentence,
        officecli_fill_table_rows,
        officecli_insert_image,
        get_full_chapter_text,
        search_bidding_document,
        extract_text_by_style,
    ] + list(db_tools)
    logger.info(f"   🛠️ [Worker 工具包] 组装完成: {len(db_tools)} DB工具 + 5 Office CLI 工具 + 2 原生 RAG 工具 + 1 样式提取工具")
    return worker_tools



# ============================================================
def extract_docx_tables_summary(docx_path: str, chapter_title: str = "") -> str:
    """
    按章节精准扫描当前 Word 文档中属于当前具体章节的待填表格物理路径、行列规模与真实表头定义。
    仅将当前章节专属的具体表格表头呈现给该 Worker，彻底消除跨章节异表干扰。
    """
    if not docx_path or not os.path.exists(docx_path):
        return ""
    try:
        from docx import Document
        from app.utils.table_utils import detect_table_header_rows, get_merged_header_texts, get_chapter_specific_table_indices
        doc = Document(docx_path)
        if not doc.tables:
            return ""

        target_tbl_indices = get_chapter_specific_table_indices(doc, chapter_title)
        if not target_tbl_indices:
            return ""

        tables_info = []
        for tbl_idx in target_tbl_indices:
            if 0 <= tbl_idx < len(doc.tables):
                table = doc.tables[tbl_idx]
                if not table.rows:
                    continue
                hdr_count = detect_table_header_rows(table)
                headers = get_merged_header_texts(table, hdr_count)
                if not any(headers):
                    continue
                tbl_path = f"/body/tbl[{tbl_idx + 1}]"
                headers_str = " | ".join(headers)
                hdr_desc = f"包含 {hdr_count} 行复合表头, " if hdr_count > 1 else ""
                tables_info.append(f"- 【本章节专属唯一目标表格】：`{tbl_path}`（共 {len(headers)} 列, {hdr_desc}预置 {len(table.rows)} 行）：真实表头定义为 `[{headers_str}]`。严禁将数据错误填报到其他章节的表格中！")

        if tables_info:
            return "\n".join(tables_info)
    except Exception as e:
        logger.warning(f"按章节提取表格表头概要异常: {e}")
    return ""


def build_worker_prompt(
    chapter_title: str,
    category: str,
    template_text: str,
    content_hint: str,
    document_id: str,
    docx_temp_path: str = "",
    mapping_hint: str = "",
    extra_instructions: str = "",
    repair_instructions: str = "",
) -> tuple:
    """构建章节 Worker Agent 的针对性专家 System Prompt 与 User Prompt（支持四类专家角色分治、真实表头注入与专项修复）。

    :param mapping_hint: 章节分类标签（如 pricing / qualification / deviation / bid_letter / authorization 等）
    :param extra_instructions: 用户自定义额外指令
    :param repair_instructions: Supervisor 下发的专项修复反馈指令
    """
    cat = (category or "needs_fill").lower().strip()
    hint = (mapping_hint or "").lower().strip()
    title_lower = (chapter_title or "").lower().strip()

    # 动态提取当前章节专属的目标表格结构与真实表头定义（严格切片，零跨章干扰）
    tables_summary = extract_docx_tables_summary(docx_temp_path, chapter_title) if docx_temp_path else ""

    # 1. 判定专家角色类型
    is_pricing = (hint in ("pricing", "cost")) or any(k in title_lower for k in ["报价", "清单", "分项", "开标一览", "主要材料"])
    is_qualification = (hint == "qualification") or any(k in title_lower for k in ["资格", "资质", "执照", "证明文件", "安全生产", "承装"])
    is_deviation = (hint in ("deviation", "technical")) or any(k in title_lower for k in ["偏离", "响应", "技术偏离", "商务偏离", "条款偏离"])

    # 2. 差异化专家工作流与职责
    if is_pricing:
        role_title = "造价工程师与分项报价专家"
        domain_workflow = f"""【造价工程师与分项报价专家工作流 — 分项全量展开铁律】
1. **结构扫描与清单检索**：
   - 调用 `officecli_query_structure(selector='table', keyword_filter='{chapter_title}')` 获取表格结构与列定义；
   - 调用 `query_financial_quotation_tool(document_id='{document_id}', field_key='cost_estimates')` 检索数据库中全量设备、材料、工程及服务清单与测算价格。
2. **【分项全量展开最高铁律 — 绝对严禁仅填大类汇总行】**：
   - **全量展开强制要求**：若表格模板包含汇总大类（如序号 1、序号 2 等大类）及 `......` 占位行，**必须在汇总大类下方，将数据库中查得的全部具体标的物/设备/材料/工程施工清单细项（编号为 2.1, 2.2, 2.3... 2.K 等全部查得项）逐行完整展开并按顺序编号排列**！
   - **绝对严禁偷懒**：绝对禁止仅填报大类 1 和 2 两行而省略二级细项！每个细项必须具备明确独立的具体标的物名称、单价与分项总价；
   - **各列严格分离对齐**：第 1 列【序号】填入层级编号（如 1、2、2.1 等），第 2 列【项目/费用名称】填纯标的物名称（严禁把序号重复写在名称列）；
   - **【单价】与【分项总价】列严格分离与对齐规范**：
     * **设备材料采购细项**（具有明确单价与数量/工程量的标的物）：【单价】列填单价数值（如按台/套/块计价），【分项总价】列填数量 × 单价之合价；
     * **按项包干/工程安装/大类汇总/未细分单价项**（如建设费汇总大类、加固工程、防水工程、电缆敷设、设计费等）：【单价】列填破折号 `"——"` 或留空，【分项总价】列填写该项的总金额；**绝对严禁将整项包干大额总金额错误复制到单价列**！
     * **不单独计取/包含在总价内/0元项目**（如设计费 0.00）：【单价】列填 `"——"`（或 `0.00`），【分项总价】列填 `0.00`；
     * **各列严格独立对齐**：必须严格根据表头列序逐列对应，确保【单价】与【分项总价】两列数据精准独立，绝不错列、串列或重复填报！
   - **占位符全量覆盖**：细分数据行必须全量自动覆盖替换模板原有的 `......` 和空白数据行，严禁残留；
   - **备注列默认留空**：【备注】列默认保持留空 `""`，无需长篇赘述，保持表格清爽；
   - **金额层级平衡**：所有 N.1~N.K 细项合价之和必须精准等于所属大类 N 的总额，所有一级大类总额之和必须精准等于表尾【合计总价】（大写与小写一致）。
3. **整表 2D 矩阵一次性写盘**：
   - 必须将大类 1、大类 2、全部展开细项（如 2.1, 2.2, ... 2.K）以及表尾合计总价行组合为一个完整的 2D 数据矩阵，调用 `officecli_fill_table_rows(table_path, rows_json_str)` 一次性提交写盘，原位覆盖并彻底清除模板原有的空白行和 `......` 占位符！"""
    elif is_qualification:
        role_title = "资格审查与资质证明专家"
        domain_workflow = f"""【资格审查与资质证明专项工作流 — 原位图像嵌入】
1. **扫描识别条款要求**：使用 `officecli_query_structure(selector='paragraph', keyword_filter='{chapter_title}')` 扫描章节内全部资格审查条款及证明材料清单要求。
2. **企业资质档案库精准检索**：
   - 提取各条款要求提供的资质类型关键词（如基础资质证明、行业许可、体系认证等通用类别）；
   - 针对各条款要求，分别调用 `query_company_qualification_tool(category='资质类别关键词')` 检索对应的合法资质证书或证明图片路径。
3. **资质图片必须调用专用工具（严禁正文打印路径文本）**：
   - 查得资质证明图片后，**必须且仅允许调用 `officecli_insert_image(target_path, image_path, caption='证书名称')` 工具**将图片原位嵌入在对应条款正下方；
   - **严禁在正文字符串中直接打印资质图片本地文件路径等字面量**；
   - **严禁将核心资质证明遗漏或误堆砌到文档其他章节**，必须 100% 严格在《资格证明文件》章节对应条款后原位落盘！"""
    elif is_deviation:
        role_title = "商务合规与技术响应专家"
        domain_workflow = f"""【偏离表与实质性条款响应专项工作流 — 允许全量生成与覆盖重写】
1. **扫描识别目标表格结构**：使用 `officecli_query_structure(selector='table', keyword_filter='{chapter_title}')` 获取表格路径与列定义。
2. **原文件整章全量阅读与交叉检索**：
   - **必须调用 `get_full_chapter_text('{document_id}', chapter_name)` 检索原招标文件对应章节全量原文**（如第四章项目需求、技术规格、合同条款或商务要求章节），获取全部条款与技术规格细节！
3. **【表格全量覆盖重写授权 (Full Table Matrix Overwrite)】**：
   - **全面重写与覆盖原表格数据行**：你有完全的权限使用 `officecli_fill_table_rows(table_path, rows_json_str)` 从序号 1 开始将所有梳理出的条款生成完整的二维矩阵，一次性覆写替换原表格的所有明细行！
   - **杜绝单点打补丁**：严禁受限于原模板历史残留的空行或部分行，必须从序号 1 到 N 全量生成整张完整规范的对照表！
4. **条款逐条独立拆分填报规范（一事一行，严禁合并挤压，覆盖全部表格行）**：
   - **一事一行独立呈现**：严禁将多个独立条款强行合并压缩到同一行！必须将原招标文件中的所有各项独立条款与参数指标约束（包括各项商务约束、技术参数、履约要求等）**逐条独立拆分为单独的数据行**，保证表格所有行均得到充分、清晰的逐条响应！
   - **各列严格对齐填报规范**：
     * **第 1 列 `tc[1]`【序号】**：填入连续纯序号数字 `1, 2, 3...`，严禁长文本混入；
     * **第 2 列 `tc[2]`【招标文件要求】**：完整原样呈现原招标文件对应条款条文，严禁使用 `...` 截断；
     * **第 3 列 `tc[3]`【服务承诺与技术响应/是否响应】**：若表头为“是否响应（填是或者否）”，统一填写“是”；若表头为“响应情况/技术承诺”，详细列明所投指标响应及法律承诺；
     * **第 4 列 `tc[4]`【有无偏离】**（若有）：统一填写“无偏离”或“无”；
     * **第 5 列 `tc[5]`【偏离内容及原因】**（若有）：统一填写“完全响应招标文件要求，无偏离。”。
5. **高效提报方式（首选 officecli_fill_table_rows 一次性全量写盘）**：
   - 必须优先直接调用 `officecli_fill_table_rows(table_path, rows_json_str)` 一次性提交整张表格的全部数据行（每行按表头列数装配 `["序号", "招标文件要求", "是/服务承诺", ...]`，底层引擎会自动保留表头并以全新数据行全量覆写原表格数据区）；
   - 严禁对表格单元格零敲碎打地调用 write_slot_value 局部打补丁！"""
    else:
        role_title = "公文函件与表单填报专家"
        domain_workflow = f"""【法定公文函件与表单填报专项工作流 — 原位切片注入】
1. **全形态槽位扫描识别（下划线 / 括号 / 纯空格留白）**：
   - 使用 `officecli_query_structure(selector='all', keyword_filter='{chapter_title}')` 扫描章节内的所有待填槽位；
   - **必须覆盖全部空白留白形态**：
     * **符号形态**：下划线 `______`、括号 `( )` 或 `[ ]`；
     * **空格留白形态**：属性标签或冒号后的**连续空格、制表符留白**（如 `通讯地址：              `、`联系电话：          `）；
     * **日期留白形态**：年月日之间的留白空格（如 `    年    月    日`）；
     凡是属于待填信息的空白区域，一律属于合法填报目标！
2. **企业档案库精准检索与主体匹配**：
   - 调用企业信息库（`query_company_basic_info`）、人员库（`query_company_personnel_tool`）、财务业绩库检索真实数据；
   - 严格根据招标文件上下文区分收件单位（如致代理机构或采购人）、组织单位与投标方主体，准确填入官方全称。
3. **原位原子写盘与纯数据提交**：
   - 必须使用 `officecli_batch_fill_sentence(updates_json_str)` 或 `officecli_write_slot_value` 进行一次性原子更新；
   - 提交的数据必须是**纯数据值**（绝对不包含前缀标签），底层引擎会自动将冒号后的纯空格/下划线精准替换为该数据值并附带下划线。"""

    system_prompt = f"""你是标书【{role_title}】，负责直接对 Word 标书文档的【{chapter_title}】章节进行深度信息检索与原位写盘操作。

【最高铁律 — 原文零改动与高质量填报法则】
1. **模板原文 100% 盲守**：绝对严禁删除、篡改、润色、删减或遗漏任何模板原文（包括前缀标签如“项目名称：”、“招标编号：”、“致：”、标点符号及授权声明等全部固定文本）！
2. **仅精准替换占位符**：只针对模板中的下划线 `______`、括号 `( )`、`[待填]` 槽位填充检索到的真实数据，非占位符的原文必须 100% 原封不动完整保留！
3. **表头感知与逐列精准对齐填报（按表头给出完整提案）**：
   - **认真研读表头定义**：必须根据 User Prompt 中【文档中检测到的实际表格与真实表头定义】，明确当前表格的列数与每一列的中文表头名称；
   - **严格按列装配真实数据**：调用数据库或原文检索工具获取数据后，**必须严格按表头定义的列序逐列对齐装配数据**（每一列分别对应表头名称，严禁错列、漏列、跨列挤压）；
   - **完整提交结构化提案**：必须通过调用 `officecli_fill_table_rows(table_path, rows_json_str)` 工具提交二维数据矩阵，或输出标准 JSON 提案列表提交所有单元格，确保表头下的所有行与列全部完整填满，严禁留下空白单元格！
4. **零容忍任何省略号与伪装标记（严禁 `...` / `……` / `…` / `（完整技术要求）`）**：
   在生成任何条款、响应或表格内容时，**绝对禁止在句子开头、句中连接处或末尾使用任何形式的省略号（包括 `…`、`……`、`...`、`..`）**！
   - 严禁使用省略号截断或连接多个指标；
   - 多个技术指标或分项承诺必须使用中文逗号 `，` 或分号 `；` 完整书写连接，严禁添加『（完整技术要求）』等任何摘要假标签！每一条响应必须是一字一句、语法完整、表述严谨的完整中文法律承诺闭合语句！
5. **【绝对禁止携带原文前缀与标签】**：
   若目标段落/槽位原文本包含字段属性名标签（例如 `"XXX名称：______"` 或 `"XXX编号：______"`），提交的替换数据 `value` **绝对禁止包含"XXX名称："等前缀标签，仅允许填入纯粹的数据值！**
   - 正确写法 (纯数据)：`value = "XXX内容值"`
6. **查无结果立刻止步**：若 DB 工具返回 "未找到..."、"尚未录入" 或空记录，**严禁换用类似关键词重复循环调库**！应当立即将该槽位标记为 "[待补充: <字段名>]"，并直接完成该句/表单写盘。绝对严禁捏造假数据！
7. **【严禁重复盲目查询 — 快速闭环铁律】**：当你从 Prompt 或 `officecli_query_structure` 已经明确当前章节的目标表格路径（如 `/body/tbl[N]`）及表头定义后，**绝对禁止使用各种同义词（如‘偏离表’、‘供货一览表’、‘开标一览表’等）重复调用 query 工具**！明确表格路径后，必须立即调用 `officecli_fill_table_rows` 或 `officecli_write_slot_value` 提交写盘提案并完成总结，迅速闭环！

{domain_workflow}

【输出总结格式要求 — 必须包含 Markdown 表格】
在完成所有读写工具调用后，请给出一份操作总结，**必须在总结末尾输出如下格式的 Markdown 明细表格**：
| 序号 | DOM 节点路径 | 替换前模板原文 | 实际填入/扩写结果 | 提议类型 | 写盘状态 |
- 第 3 列 (替换前模板原文)：填入替换前未修饰的原始模板文本（如 `"XXX属性：______"` 或表格单元格原文）；
- 第 4 列 (实际填入/扩写结果)：【纯数据填充】如果提议类型是 `text`，仅允许填写纯数据值；如果是 `image`，填入图片绝对路径；如果是 `sentence_batch`，填入覆盖重写后的完整新段落。严禁使用 `**` 加粗标记；
- 第 5 列 (提议类型)：必须严格填写以下之一："text"、"image"、"sentence_batch"。"""

    if extra_instructions:
        system_prompt += f"""

【用户单章节专属重新生成与微调指令 — 最高优先级】
当前任务为单章节重新生成与覆写，必须与主流程初次生成完全一致：
1. **源头全量检索**：根据具体的表格表头与章节要求，主动调用查原文工具（`get_full_chapter_text`、`search_bidding_document`）或企业数据库工具，从源头完整检索所有条款、技术参数与业务数据；
2. **整表全量覆写**：针对表格章节，必须从序号 1 开始将所检索出的全部条文装配为完整的二维数据矩阵，调用 `officecli_fill_table_rows(table_path, rows_json_str)` 全量覆写原表格，严禁受历史半成品残留影响做局部打补丁！
3. **用户微调要求**：
{extra_instructions}"""

    if repair_instructions:
        system_prompt += f"""

【专项修复紧急指令 — Supervisor 质量审核反馈】
Supervisor 在上一轮审核中发现以下问题，请优先对该章节实施专项补救与重新写盘：
{repair_instructions}"""

    tables_part = f"\n\n【文档中检测到的实际表格与真实表头定义】\n{tables_summary}" if tables_summary else ""

    user_prompt = f"""【撰写任务】
- 文档 ID: {document_id}
- 章节标题: {chapter_title}
- 任务类别: {category}
- 映射标签: {mapping_hint or '通用'}{tables_part}

【甲方原文模板】
{template_text or '（按招标要求智能撰写）'}

【填写说明】
{content_hint or '（无特殊说明）'}

请根据专家专项工作流开启工具调取与写盘，完成【{chapter_title}】章节的智能撰写。"""

    return system_prompt, user_prompt



# ============================================================
# Worker 执行器
# ============================================================

def run_chapter_worker(
    chapter_title: str,
    chapter_number: str,
    mapping_hint: str,
    category: str,
    document_id: str,
    docx_temp_path: str,
    template_text: str = "",
    content_hint: str = "",
    extra_instructions: str = "",
    repair_instructions: str = "",
) -> Dict[str, Any]:
    """
    为单个章节创建独立 ReAct Agent 并直接执行读写 Word 盘块操作。

    :param extra_instructions: 用户自定义额外指令
    :param repair_instructions: Supervisor 质量审核反馈的专项修复指令
    :return: {chapter_title, mapping_hint, status, summary, error}
    """
    cat = (category or "needs_fill").lower().strip()
    logger.info(f"[Worker Direct-Fill] 启动撰写 Agent → [{chapter_title}] (类别: {cat})")
    if repair_instructions:
        logger.warning(f"[Worker 专项修复模式] 接收到 Supervisor 反馈指令: {repair_instructions[:100]}...")

    if cat in ("needs_writing", "skip"):
        logger.info(f"⏩ [Worker] [{chapter_title}] 属于 {cat}，跳过撰写")
        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "skipped",
            "proposals": [], "summary": f"跳过 ({cat})",
        }

    if not hasattr(llm_service, 'raw_llm') or llm_service.raw_llm is None:
        return {"chapter_title": chapter_title, "mapping_hint": mapping_hint,
                "category": cat, "status": "failed", "proposals": [],
                "error": "LLM not initialized"}

    try:
        chapter_collected_proposals: List[Dict[str, Any]] = []
        worker_tools = _build_worker_tools(docx_temp_path=docx_temp_path, chapter_title=chapter_title, collected_proposals=chapter_collected_proposals)
        system_prompt, user_prompt = build_worker_prompt(
            chapter_title=chapter_title, category=cat,
            template_text=template_text, content_hint=content_hint,
            document_id=document_id,
            docx_temp_path=docx_temp_path,
            mapping_hint=mapping_hint,
            extra_instructions=extra_instructions,
            repair_instructions=repair_instructions,
        )


        # [优化点1：零度确定性控制] 常规表单与表格清单填写必须无限强行死扣于 `temperature=0.0`；长文本限制于0.2
        target_temp = 0.0 if cat in ("needs_fill", "needs_data", "skip") else 0.2
        worker_llm = llm_service.get_llm(temperature=target_temp, json_mode=False)
        if not worker_llm:
            worker_llm = llm_service.raw_llm
        logger.info(f"Worker [{chapter_title}] ({cat}) → 分配模型温度 (temperature={target_temp})")

        # 详细打印大模型初始输入（System Prompt 与 User Prompt 概况）
        logger.info(
            f"🚀 [LLM Prompt 准备发送] [{chapter_title}] | System Prompt: {len(system_prompt)} 字符 | "
            f"User Prompt: {len(user_prompt)} 字符 | 工具集数量: {len(worker_tools)}"
        )
        logger.info(f"   📋 [User Prompt 完整内容]:\n{user_prompt}")
        if extra_instructions:
            logger.info(f"   🎯 [注入的微调提示词]: '{extra_instructions}'")

        agent = create_react_agent(worker_llm, worker_tools)
        import time
        t_start = time.time()

        # 自动重试机制（针对网络波动与大模型 API 连接限流进行容错退避）
        max_retries = 3
        result = None
        for attempt in range(1, max_retries + 1):
            try:
                result = agent.invoke(
                    {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": 50}
                )
                break
            except Exception as err:
                err_str = str(err).lower()
                is_conn_err = any(k in err_str for k in ["connection", "timeout", "reset", "disconnected", "http", "rate", "500", "502", "503", "504"])
                logger.error(f"[Worker 异常调用报错] [{chapter_title}] 第 {attempt} 次失败: {err}")
                if is_conn_err and attempt < max_retries:
                    backoff = attempt * 2.0
                    logger.warning(f"[Worker 网络重试] [{chapter_title}] 等待 {backoff:.1f}s 后自动重试...")
                    time.sleep(backoff)
                else:
                    raise err

        t_end = time.time()
        final_msg = result["messages"][-1].content
        
        # 提取全量 ReAct 中间思考步骤 (Intermediate Thought Steps)
        thought_steps = []
        step_idx = 1
        for msg in result.get("messages", []):
            msg_type = type(msg).__name__
            if msg_type == "AIMessage":
                content = getattr(msg, "content", "")
                tool_calls = getattr(msg, "tool_calls", [])
                if content or tool_calls:
                    thought_steps.append({
                        "step": step_idx,
                        "type": "thought",
                        "thought": content,
                        "tool_calls": tool_calls
                    })
                    step_idx += 1
            elif msg_type == "ToolMessage":
                thought_steps.append({
                    "step": step_idx - 1,
                    "type": "tool_result",
                    "name": getattr(msg, "name", "tool"),
                    "output": str(getattr(msg, "content", ""))[:1500]
                })

        tool_calls_count = sum(1 for m in result["messages"] if hasattr(m, 'tool_calls') and m.tool_calls)

        # 1. 解析文本输出中的提案
        text_proposals = _parse_proposals(final_msg)

        # 2. 双路融合：Tool-First 原则（工具调用捕获的结构化提案为最高权威，绝对禁止被文本概括覆写）
        proposals_dict = {}

        # 先合入文本提取的辅助提案
        for p in text_proposals:
            p_path = str(p.get("path", "")).strip()
            if p_path:
                proposals_dict[p_path] = p

        # 随后合入工具调用捕获的权威提案（具有最高优先级）
        for p in chapter_collected_proposals:
            p_path = str(p.get("path", "")).strip()
            if p_path:
                proposals_dict[p_path] = p
                # 仅当工具捕获了【整表 2D 矩阵提案】(/body/tbl[N]) 时，才清理文本提取的该表下行级/单元格级冗余提案
                # 必须严格全字匹配 ^/body/tbl\[\d+\]$，严禁误删单单元格提案！
                if p.get("type") == "table_rows" or re.match(r'^/body/tbl\[\d+\]$', p_path):
                    m_tbl = re.match(r'^(/body/tbl\[\d+\])$', p_path)
                    if m_tbl:
                        tbl_prefix = m_tbl.group(1)
                        to_del = [k for k in proposals_dict.keys() if k.startswith(tbl_prefix + "/") and k != p_path]
                        for k in to_del:
                            logger.info(f"   [Tool-First 保护] 工具已提供权威整表 {tbl_prefix} 提案，剔除文本提取的行级伪提案: {k}")
                            proposals_dict.pop(k, None)

        proposals = list(proposals_dict.values())
        logger.info(f"   [Worker 提案汇聚] [{chapter_title}] 工具捕获 {len(chapter_collected_proposals)} 条 + 文本解析 {len(text_proposals)} 条 -> 融合去重后共 {len(proposals)} 条有效写盘提案")
        n = len(proposals)

        # 2. 提取 Token 消耗与审计事件记录
        p_tok, c_tok = 0, 0
        for m in result.get("messages", []):
            if hasattr(m, "response_metadata") and isinstance(m.response_metadata, dict):
                usage = m.response_metadata.get("token_usage") or m.response_metadata.get("usage") or {}
                p_tok += usage.get("prompt_tokens", 0)
                c_tok += usage.get("completion_tokens", 0)

        from app.services.audit_service import audit_service
        audit_service.log_event(
            action_type="llm_call_worker",
            node_name=f"BidFillerWorker-{chapter_title[:30]}",
            inputs={"chapter_title": chapter_title, "category": cat, "document_id": document_id},
            outputs={
                "proposals_count": n,
                "proposals": proposals,
                "summary": final_msg,
                "thought_steps": thought_steps
            },
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            execution_time_ms=int((t_end - t_start) * 1000),
            status="success"
        )

        # 记录 Worker 完整诊断上下文（供导出日志排查）
        _record_worker_context(
            doc_id=document_id,
            chapter_title=chapter_title,
            category=cat,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            final_msg=final_msg,
            tool_calls=tool_calls_count,
            proposals=proposals
        )

        # 存入全局提案池（供 Review Agent 读取）
        if proposals:
            with _PROPOSALS_LOCK:
                if document_id not in _WORKER_PROPOSALS:
                    _WORKER_PROPOSALS[document_id] = []
                for p in proposals:
                    p["chapter_title"] = chapter_title
                    p["mapping_hint"] = mapping_hint
                _WORKER_PROPOSALS[document_id].extend(proposals)

        logger.info(
            f"[Worker Agent 完成] [{chapter_title}] | 耗时: {int((t_end - t_start) * 1000)}ms | "
            f"工具调用: {tool_calls_count} 次 | 提案: {n} 个 | "
            f"Prompt Tokens: {p_tok:,} | Completion Tokens: {c_tok:,} | Total: {p_tok + c_tok:,}"
        )
        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "success",
            "tool_calls": tool_calls_count,
            "proposals_count": n,
            "proposals": proposals,
            "summary": final_msg,
        }

    except Exception as e:
        logger.error(f"[Worker] [{chapter_title}] 失败: {e}")
        try:
            from app.services.audit_service import audit_service
            audit_service.log_event(
                action_type="llm_call_worker",
                node_name=f"BidFillerWorker-{chapter_title[:30]}",
                inputs={"chapter_title": chapter_title, "category": cat, "document_id": document_id},
                outputs={
                    "summary": f"Worker 章节填报发生异常: {str(e)[:200]}",
                    "error": str(e)[:500]
                },
                status="failed"
            )
        except Exception as log_err:
            logger.warning(f"写入 Worker 异常审计日志失败: {log_err}")

        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "failed", "proposals": [],
            "error": str(e)[:500],
        }


def _normalize_proposal_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """归一化单个提案对象，统一对齐 proposed_text 与 value 键名，并过滤虚假概括行"""
    if not isinstance(item, dict):
        return None
    import re
    path = str(item.get("path", "")).strip().replace("`", "")
    if not path:
        return None
    # 过滤包含 ~ 或 .. 的概括性假路径 (如 /body/tbl[2]/tr[2]~tr[17] 或 /body/tbl[2]/tr[2..17])
    if "~" in path or ".." in path:
        return None

    # 提取有效文本内容：优先 proposed_text，次选 value，再选 text
    val = item.get("proposed_text")
    if val is None:
        val = item.get("value")
    if val is None:
        val = item.get("text")
    if val is None:
        val = ""

    val_str = str(val).strip().replace("`", "").replace("**", "")
    # 若内容为空且非特殊类型，丢弃
    if not val_str and item.get("type") != "image":
        return None

    res = dict(item)
    res["path"] = path
    res["proposed_text"] = val_str
    res["value"] = val_str
    if "status" not in res:
        res["status"] = "success"
    return res


def _repair_json_unescaped_quotes(json_str: str) -> str:
    """自动对 JSON 字符串值中未经转义的半角双引号进行容错替换"""
    import re
    def fix_field_val(m):
        prefix = m.group(1)   # `"reasoning": "`
        content = m.group(2)  # `原文"招标编号..."`
        suffix = m.group(3)   # `"`
        fixed_content = content.replace('"', '”')
        return f'{prefix}{fixed_content}{suffix}'
    pattern = r'("(?:path|original_context|source_data|source_tool|proposed_text|value|text|reasoning|chapter_title|mapping_hint)"\s*:\s*")([\s\S]*?)("\s*[,\}])'
    return re.sub(pattern, fix_field_val, json_str)


def _parse_proposals(raw_text: str) -> List[Dict[str, Any]]:
    """从 Worker 的最终回复中提取 JSON 提案列表（包含多重智能容错、双向键名归一化与融合提取机制）"""
    import re
    if not raw_text:
        return []
    cleaned = raw_text.strip()
    raw_json_candidates = []

    # 策略1: 提取 ```json ... ``` 代码块
    if "```" in cleaned:
        for match in re.finditer(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', cleaned):
            cand_str = match.group(1).strip()
            if cand_str:
                raw_json_candidates.append(cand_str)

    # 策略2: 直接解析全文
    raw_json_candidates.append(cleaned)

    # 策略3: 从混合文本中提取 JSON 数组（贪婪匹配）
    for pattern in [r'\[\s*\{[\s\S]*\}\s*\]', r'\[\s*\{[\s\S]*?\}\s*\]']:
        m = re.search(pattern, cleaned)
        if m:
            raw_json_candidates.append(m.group(0))

    parsed_json_items: List[Dict[str, Any]] = []
    for cand in raw_json_candidates:
        if not cand:
            continue
        # 尝试标准解析
        try:
            data = _json.loads(cand)
            if isinstance(data, list):
                parsed_json_items = data
                break
            if isinstance(data, dict) and "proposals" in data and isinstance(data["proposals"], list):
                parsed_json_items = data["proposals"]
                break
        except Exception:
            pass

        # 尝试修复尾部逗号与未转义双引号后解析
        try:
            fixed = re.sub(r',\s*\]', ']', cand)
            fixed = re.sub(r',\s*\}', '}', fixed)
            data = _json.loads(fixed)
            if isinstance(data, list):
                parsed_json_items = data
                break
        except Exception:
            pass

        try:
            repaired = _repair_json_unescaped_quotes(cand)
            repaired = re.sub(r',\s*\]', ']', repaired)
            repaired = re.sub(r',\s*\}', '}', repaired)
            data = _json.loads(repaired)
            if isinstance(data, list):
                parsed_json_items = data
                break
        except Exception:
            pass

    # 策略4: 对象级逐项恢复机制
    if not parsed_json_items:
        obj_matches = re.finditer(r'\{\s*"path"\s*:[\s\S]*?\}', raw_text)
        for m in obj_matches:
            candidate = m.group(0)
            try:
                item = _json.loads(candidate)
                if isinstance(item, dict) and "path" in item:
                    parsed_json_items.append(item)
                    continue
            except Exception:
                pass
            try:
                repaired_cand = _repair_json_unescaped_quotes(candidate)
                item = _json.loads(repaired_cand)
                if isinstance(item, dict) and "path" in item:
                    parsed_json_items.append(item)
            except Exception:
                pass

    # 策略5: 从 Markdown 表格行提取提案明细（补充提取与融合）
    markdown_table_items: List[Dict[str, Any]] = []
    tbl_row_counters: Dict[str, int] = {}

    if "|" in raw_text:
        for line in raw_text.split("\n"):
            l_str = line.strip()
            if not l_str.startswith("|") or "---" in l_str or "序号" in l_str or "DOM 节点" in l_str or "替换前" in l_str or "检索结果" in l_str or "数据项" in l_str:
                continue
            # 跳过仅作为保护声明的表头保护行
            if any(k in l_str for k in ["表头原样保留", "已保护", "未改动", "未修改", "原样保留"]):
                continue
            cells = [c.replace("`", "").replace("**", "").strip() for c in l_str.split("|") if c.strip()]
            if len(cells) >= 3:
                path_col_idx = -1
                for idx, cell in enumerate(cells):
                    if re.search(r'(/[a-zA-Z0-9\[\]\@\=\:\-\_\.\~]+)+', cell):
                        path_col_idx = idx
                        break

                if path_col_idx == -1:
                    continue

                path_val = cells[path_col_idx]
                path_m = re.search(r'(/[a-zA-Z0-9\[\]\@\=\:\-\_\.\~]+)+', path_val)
                if path_m:
                    path_val = path_m.group(0)

                # 智能自愈：若大模型在 Markdown 表格中使用了范围概括路径 (如 /body/tbl[6]/tr[2]~tr[19] 或 /body/tbl[6]/tr[2..19])
                # 自动按表格出现顺序展开为连续递增的物理行路径 tr[2], tr[3], tr[4]... 彻底杜绝多行数据被误删丢弃！
                m_range = re.search(r'(/body/tbl\[\d+\])(?:/tr\[\d+\])?(?:~|\.\.)tr\[(\d+)\]', path_val)
                m_base_tbl = re.search(r'(/body/tbl\[\d+\])', path_val)
                if m_range or ("~" in path_val or ".." in path_val):
                    tbl_base = m_range.group(1) if m_range else (m_base_tbl.group(1) if m_base_tbl else "/body/tbl[1]")
                    curr_r = tbl_row_counters.get(tbl_base, 2)
                    path_val = f"{tbl_base}/tr[{curr_r}]"
                    tbl_row_counters[tbl_base] = curr_r + 1
                elif m_base_tbl and "/tr[" in path_val and "/tc[" not in path_val:
                    # 若连续多行使用相同的单行路径 (如都是 /body/tbl[6]/tr[2])，自动递增行号
                    tbl_base = m_base_tbl.group(1)
                    curr_r = tbl_row_counters.get(tbl_base, 2)
                    path_val = f"{tbl_base}/tr[{curr_r}]"
                    tbl_row_counters[tbl_base] = curr_r + 1
                elif m_base_tbl:
                    tbl_base = m_base_tbl.group(1)
                    m_tr_num = re.search(r'/tr\[(\d+)\]', path_val)
                    if m_tr_num:
                        tbl_row_counters[tbl_base] = max(tbl_row_counters.get(tbl_base, 2), int(m_tr_num.group(1)) + 1)

                # 自动自愈尾部缺失右括号
                path_val = re.sub(r'/tc\[(\d+)$', r'/tc[\1]', path_val)
                path_val = re.sub(r'/cell\[(\d+)$', r'/cell[\1]', path_val)
                path_val = re.sub(r'/tr\[(\d+)$', r'/tr[\1]', path_val)

                orig_val = cells[path_col_idx + 1] if path_col_idx + 1 < len(cells) else ""
                prop_val = cells[path_col_idx + 2] if path_col_idx + 2 < len(cells) else ""

                prop_type = "text"
                is_cell_path = bool(re.search(r'/(?:tr|row|tc|cell)\[\d+\]', path_val))
                if path_col_idx + 3 < len(cells):
                    t_str = cells[path_col_idx + 3].lower()
                    if "image" in t_str or "图片" in t_str:
                        prop_type = "image"
                    elif "sentence_batch" in t_str or "覆盖" in t_str:
                        prop_type = "sentence_batch"
                    elif ("table_rows" in t_str or "插行" in t_str) and not is_cell_path:
                        prop_type = "table_rows"

                prop_val = prop_val.replace("**", "").replace("`", "").strip()

                # 通用规则 1：过滤大模型在总结时输出的运算符伪拼接表达式 (如 'A + B + C' 或 '"A" + "B"')
                if re.search(r'(?:\S\s*\+\s*\S|\"\s*\+\s*\")', prop_val):
                    logger.warning(f"   [通用提案过滤] 拦截到伪拼接表达式文本，拒绝提取: path={path_val}, val={prop_val[:50]}")
                    continue

                # 通用规则 2：过滤纯元数据状态词 (如状态标记、占位省略符)
                if prop_val in ("—", "-", "--", "同上", "略", "无变更", "原样保留") or re.match(r'^(?:已|未)[^\s]{1,6}(?:队列|保护|修改|变更|填报)$', prop_val):
                    continue

                # 通用规则 3：表格路径与类型严格归一化
                # 如果是整表路径 (/body/tbl[N])，必须能够成功反序列化为合法的 2D 矩阵 (list of lists)，否则判定为无效表格提案
                if bool(re.search(r'^/body/tbl\[\d+\]$', path_val)):
                    try:
                        parsed_m = _json.loads(prop_val)
                        if isinstance(parsed_m, list) and parsed_m and isinstance(parsed_m[0], list):
                            prop_type = "table_rows"
                        else:
                            continue
                    except Exception:
                        continue
                elif bool(re.search(r'/tbl\[\d+\]/(?:tr|row)\[\d+\]$', path_val)):
                    # 若非 sentence_batch 且不含多列分隔符，过滤行级模糊单文本路径防止错列
                    if prop_type not in ("sentence_batch", "table_rows") and not any(s in prop_val for s in ["|", "｜", "\t"]):
                        logger.warning(f"   [通用提案过滤] 行级路径未指定具体单元格 (tc/cell)，跳过单文本提炼: {path_val}")
                        continue

                markdown_table_items.append({
                    "path": path_val,
                    "original_context": orig_val,
                    "proposed_text": prop_val,
                    "value": prop_val,
                    "type": prop_type,
                    "status": "success"
                })

    # 6. 双向归一化与融合去重（优先保留更精确的提议类型与上下文）
    normalized_dict: Dict[str, Dict[str, Any]] = {}

    for it in parsed_json_items:
        norm = _normalize_proposal_item(it)
        if norm:
            p_key = norm["path"]
            if p_key not in normalized_dict:
                normalized_dict[p_key] = norm

    # 融合 Markdown 表格提取项（补充缺失行，并提升 JSON 中可能被泛化的提议类型）
    for it in markdown_table_items:
        norm = _normalize_proposal_item(it)
        if norm:
            p_key = norm["path"]
            if p_key not in normalized_dict:
                normalized_dict[p_key] = norm
            else:
                existing = normalized_dict[p_key]
                # 若 JSON 项为通用 "text" 且 Markdown 表格标记了更具体的 sentence_batch / table_rows / image，提升之
                if existing.get("type") in ("text", "", None) and norm.get("type") in ("sentence_batch", "table_rows", "image"):
                    existing["type"] = norm.get("type")
                if not existing.get("original_context") and norm.get("original_context"):
                    existing["original_context"] = norm.get("original_context")

    normalized_list = list(normalized_dict.values())

    if normalized_list:
        logger.info(f"   [Worker 提案提炼成功] 归一化并融合产出 {len(normalized_list)} 条合法提案明细")
        return normalized_list

    logger.warning(f"   [Worker] 无法解析提案 JSON ({len(raw_text)} 字符):\n{raw_text[:500]}...")
    return []


# ============================================================
# Worker 上下文日志导出管理
# ============================================================
_WORKER_CONTEXT_LOGS: Dict[str, List[Dict[str, Any]]] = {}
_CONTEXT_LOCK = _threading.Lock()

def _record_worker_context(
    doc_id: str,
    chapter_title: str,
    category: str,
    system_prompt: str,
    user_prompt: str,
    final_msg: str,
    tool_calls: int,
    proposals: List[Dict[str, Any]]
):
    with _CONTEXT_LOCK:
        if doc_id not in _WORKER_CONTEXT_LOGS:
            _WORKER_CONTEXT_LOGS[doc_id] = []
        _WORKER_CONTEXT_LOGS[doc_id].append({
            "chapter_title": chapter_title,
            "category": category,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "final_msg": final_msg,
            "tool_calls": tool_calls,
            "proposals_count": len(proposals),
            "proposals": proposals,
        })

def export_worker_context_log(doc_id: str) -> str:
    """将指定文档的所有 Worker 子 Agent 运行时上下文导出为独立的 Markdown 审计日志文件"""
    with _CONTEXT_LOCK:
        logs = _WORKER_CONTEXT_LOGS.get(doc_id, [])

    output_dir = os.path.join(os.getcwd(), "outputs", "human_fill_results")
    os.makedirs(output_dir, exist_ok=True)
    report_file = os.path.join(output_dir, f"worker_agent_context_log_{doc_id[:8]}.md")

    md_lines = [
        f"# Worker 子 Agent 运行时完整上下文诊断报告",
        f"- **文档 ID**: `{doc_id}`",
        f"- **已完成 Worker 数**: `{len(logs)}`",
        f"- **生成时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
        "---",
        ""
    ]

    for idx, ctx in enumerate(logs, 1):
        md_lines.append(f"## [{idx}] Worker 章节: {ctx['chapter_title']} (类别: {ctx['category']})")
        md_lines.append(f"- **工具调用次数**: `{ctx['tool_calls']}`")
        md_lines.append(f"- **产出提案数**: `{ctx['proposals_count']}`")
        md_lines.append("")
        md_lines.append("### 1. System Prompt (系统提示词)")
        md_lines.append("```text")
        md_lines.append(ctx['system_prompt'])
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("### 2. User Prompt (用户任务与模板输入)")
        md_lines.append("```text")
        md_lines.append(ctx['user_prompt'])
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("### 3. ReAct LLM 终端回复原文")
        md_lines.append("```text")
        md_lines.append(ctx['final_msg'])
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("### 4. 最终提炼的 Proposals 提案清单")
        md_lines.append("```json")
        md_lines.append(_json.dumps(ctx['proposals'], ensure_ascii=False, indent=2))
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    content = "\n".join(md_lines)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"   📄 [Worker 上下文诊断日志已导出]: {report_file}")
    return report_file
