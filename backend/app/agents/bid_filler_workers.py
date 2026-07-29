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

# 全局提案收集池（线程安全，key 为 document_id）
_PROPOSALS_LOCK = __import__('threading').Lock()
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
    """
    if not raw_structure or (not target_chapter and not keyword):
        return raw_structure
    lines = [line.strip() for line in raw_structure.split("\n") if line.strip()]
    if len(lines) <= 30 and not keyword:
        return raw_structure

    search_term = keyword.strip() if keyword else target_chapter.strip()
    if not search_term:
        return raw_structure

    matched_indices = [i for i, l in enumerate(lines) if search_term in l]
    if not matched_indices and len(search_term) > 3:
        short_term = search_term[:4]
        matched_indices = [i for i, l in enumerate(lines) if short_term in l]

    if not matched_indices:
        # 若为常规不涉及精准命中的表，回退保护不过载
        return raw_structure[:3500] + ("\n...(部分跨章冗余节点已按规则保护折叠)..." if len(raw_structure) > 3500 else "")

    selected_indices = set()
    for idx in matched_indices:
        for w in range(max(0, idx - window_size), min(len(lines), idx + window_size + 1)):
            selected_indices.add(w)

    sorted_indices = sorted(selected_indices)
    filtered_lines = [lines[i] for i in sorted_indices]
    summary_hdr = (
        f"✂️ [切碎视口绝缘池 (Scope Spliced)]: 全文件 {len(lines)} 个 DOM 节点 -> 依据 '{search_term}' "
        f"聚合锁定前后 ±{window_size} 段 ({len(filtered_lines)} 个精准目标行)，已屏蔽一切异章噪音：\n"
    )
    return summary_hdr + "\n".join(filtered_lines)


def _build_worker_tools(docx_temp_path: str, chapter_title: str = "") -> List:
    """
    为 Worker 组装只读工具集：全部 6 个 DB 工具 + officecli_query_structure（附带原生切碎视口隔离）。
    Worker 不写盘 —— 产出 FillProposal 提交给 Review Agent。
    """
    db_tools = get_all_bid_db_tools()

    from app.mcp.office_cli_client import office_cli_mcp_client
    import asyncio
    import concurrent.futures
    from langchain_core.tools import tool

    def _sync_call_async(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()

    @tool
    def officecli_query_structure(selector: str = "paragraph", keyword_filter: str = "", window: int = 3) -> str:
        """
        [精准切口查询工具] 查询当前 Word 文档的 DOM 结构。
        参数：
        - selector: 'paragraph' / 'table' / 'all'
        - keyword_filter: [核心推荐] 填入想要寻找的属性关键短语（如 '总价'、'营业执照'、'法人' 或本小节标题）。系统将实施防闪移切割，且自动隔离所有无关章节！
        - window: 匹配点外延上下关联段数（默认 3 段）。
        """
        logger.info(f"   🔧 [Worker 聚焦视野] 查询文档结构 (selector='{selector}', kw='{keyword_filter}', w={window})")
        coro = office_cli_mcp_client.query_structure(docx_temp_path, selector)
        res = _sync_call_async(coro)
        raw_text = res.get("structure", str(res)) if isinstance(res, dict) else str(res)
        return _filter_dom_scope(raw_text, chapter_title, keyword_filter, window)

    worker_tools = list(db_tools) + [officecli_query_structure]
    logger.info(f"   🛠️ [Worker 工具] {len(db_tools)} DB + 1 读文档 = {len(worker_tools)} 工具（只读与精微切口，不写盘）")
    return worker_tools


# ============================================================
# Worker Prompt — 产出填写提案模式
# ============================================================

def build_worker_prompt(
    chapter_title: str,
    category: str,
    template_text: str,
    content_hint: str,
    document_id: str,
) -> tuple:
    """构建章节 Worker 的 System Prompt 和 User Prompt。Worker 产出填写建议，不写盘。"""
    cat = (category or "needs_fill").lower().strip()

    if cat == "needs_fill":
        strategy = """■ 填空调研策略:
  - 优先用 officecli_query_structure(selector='paragraph', keyword_filter='字段名或本章要务') 实施聚焦查询，隔离异章干扰
  - 识别每个空白/下划线/占位符（如"投标人名称：___"、"法定代表人：___"、"项目编号：___"）
  - 对每个空白，判断需要什么类型的数据，选择最匹配的 DB 工具查询
  - 记下：路径（如 p[51]）、原文占位符、DB 来源、查询到的原始值
  - 思考标书语言转化（公司名加"（盖章）"，金额加 ¥ 和千分位，日期中文格式）"""
    elif cat == "needs_data":
        strategy = """■ 表格调研策略:
  - 用 officecli_query_structure(selector='table', keyword_filter='表项词') 查询并聚焦本章节对应表格，切防其他表格混入
  - 分析表头列名，识别每列的业务含义
  - 根据表格类型选择 DB 工具获取数据清单（特别提醒：若是【分项报价、设备配置或BOM清单表】，务必优先调用 query_financial_quotation_tool(document_id, 'cost_estimates') 提取完整的设备名称、单价及分项合计总价；也可使用 query_market_price_reference_tool 按关键词联查参考单价和合价）
  - 记下：表格路径、表头信息、数据来源、每行每列的建议填入值"""
    else:
        strategy = """■ 自由调研策略:
  - 用 officecli_query_structure(selector='all', keyword_filter='小篇标题') 锁定局部结构
  - 识别需要填写/补充的位置
  - 查 DB 获取可用数据"""

    system_prompt = f"""你是标书编制调研专家，专门负责调研【{chapter_title}】章节。

{strategy}

【🚨 输出格式 — 违反此规则则整个调研作废】
你的最终回复必须是一个纯粹的 JSON 数组，以 [ 开头、以 ] 结尾。
❌ 禁止在 JSON 前后写任何分析、总结、说明文字！
❌ 禁止写"根据调研..."、"以下是..."等引导语！
✅ 正确格式: 直接输出 [{{"path":...,"proposed_text":...,...}}, ...]

每个提案对象包含以下字段:
- path: 如 "/body/p[1]/r[1]" 或 "/body/p[@paraId=17F154A1]/r[1]"（兼容正整数索引以及 OfficeCLI 结构化查询原生输出的 @paraId 路径定位）
- original_context: 原文该位置前后文字
- source_data: DB 查询到的原始值
- source_tool: 调用的工具函数名（如 query_company_profile_tool）
- proposed_text: 标书语言转化后的最终填入文本
- reasoning: 一句话引用原文依据

【硬约束】
- 🚫 只调研，不写盘！
- source_data 必须来自 DB，查不到则 source_data="[待补充]", source_tool="none"
- 每个查询前先确认原文中确实要求了该数据项
- 不要凭经验猜测原文没要求的资质/证书/设备名称"""

    user_prompt = f"""【调研任务】
- 文档 ID: {document_id}
- 章节标题: {chapter_title}
- 任务类别: {category}

【甲方原文模板】
{template_text or '（无模板，按招标要求调研）'}

【甲方填写说明】
{content_hint or '（无特殊说明）'}

⚠️ 你的回复必须是一个 JSON 数组，以 [ 开头，不要写任何其他文字！

请调研【{chapter_title}】章节。"""

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
) -> Dict[str, Any]:
    """
    为单个章节创建独立 ReAct Agent 并执行调研。
    Worker 产出 FillProposal 列表，不写盘。

    :return: {chapter_title, mapping_hint, status, proposals, summary, error}
    """
    cat = (category or "needs_fill").lower().strip()
    logger.info(f"⚡ [Worker] 启动调研 Agent → [{chapter_title}] (类别: {cat})")

    if cat in ("needs_writing", "skip"):
        logger.info(f"⏩ [Worker] [{chapter_title}] 属于 {cat}，跳过调研")
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
        worker_tools = _build_worker_tools(docx_temp_path=docx_temp_path, chapter_title=chapter_title)
        system_prompt, user_prompt = build_worker_prompt(
            chapter_title=chapter_title, category=cat,
            template_text=template_text, content_hint=content_hint,
            document_id=document_id,
        )

        # [优化点1：零度确定性控制] 常规表单与表格清单填写必须无限强行死扣于 `temperature=0.0`；长文本限制于0.2
        target_temp = 0.0 if cat in ("needs_fill", "needs_data", "skip") else 0.2
        worker_llm = llm_service.get_llm(temperature=target_temp, json_mode=False)
        if not worker_llm:
            worker_llm = llm_service.raw_llm
        logger.info(f"❄️ [零温防偏锁定] Worker [{chapter_title}] ({cat}) → 分配无震动恒等模型 (temperature={target_temp})")

        agent = create_react_agent(worker_llm, worker_tools)
        result = agent.invoke({
            "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        })
        final_msg = result["messages"][-1].content
        tool_calls = sum(1 for m in result["messages"] if hasattr(m, 'tool_calls') and m.tool_calls)

        # 解析 Worker 输出的 JSON 提案列表
        proposals = _parse_proposals(final_msg)

        # 存入全局提案池（供 Review Agent 读取）
        if proposals:
            with _PROPOSALS_LOCK:
                if document_id not in _WORKER_PROPOSALS:
                    _WORKER_PROPOSALS[document_id] = []
                for p in proposals:
                    p["chapter_title"] = chapter_title
                    p["mapping_hint"] = mapping_hint
                _WORKER_PROPOSALS[document_id].extend(proposals)

        n = len(proposals)
        logger.info(f"✅ [Worker] [{chapter_title}] 完成（{tool_calls} 次工具调用, {n} 个提案）")
        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "success",
            "tool_calls": tool_calls,
            "proposals_count": n,
            "summary": final_msg,
        }

    except Exception as e:
        logger.error(f"❌ [Worker] [{chapter_title}] 失败: {e}")
        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "failed", "proposals": [],
            "error": str(e)[:500],
        }


def _parse_proposals(raw_text: str) -> List[Dict[str, Any]]:
    """从 Worker 的最终回复中提取 JSON 提案列表"""
    import re
    if not raw_text:
        return []
    cleaned = raw_text.strip()
    # 策略1: 提取 ```json ... ``` 代码块
    if "```" in cleaned:
        match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', cleaned)
        if match:
            cleaned = match.group(1).strip()
    # 策略2: 直接解析全文
    try:
        data = _json.loads(cleaned)
        if isinstance(data, list): return data
        if isinstance(data, dict) and "proposals" in data: return data["proposals"]
    except Exception:
        pass
    # 策略3: 从混合文本中提取 JSON 数组（贪婪匹配，尽可能多）
    for pattern in [r'\[\s*\{[\s\S]*\}\s*\]', r'\[\s*\{[\s\S]*?\}\s*\]']:
        match = re.search(pattern, cleaned)
        if match:
            try:
                return _json.loads(match.group(0))
            except Exception:
                continue
    # 策略4: 修复常见 JSON 错误后重试（尾部多余逗号等）
    match = re.search(r'\[\s*\{[\s\S]*?\}\s*\]', cleaned)
    if match:
        try:
            fixed = re.sub(r',\s*\]', ']', match.group(0))  # 去尾部逗号
            fixed = re.sub(r',\s*\}', '}', fixed)
            return _json.loads(fixed)
        except Exception:
            pass
    logger.warning(f"   ⚠️ [Worker] 无法解析提案 JSON ({len(raw_text)} 字符):\n{raw_text}")
    return []
