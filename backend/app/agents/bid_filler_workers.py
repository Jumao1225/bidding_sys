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
    为 Worker 组装完整只读+直写工具集：
    - DB 工具：全部 6 个 DB 工具；
    - Office CLI 工具：结构查询、单槽位写盘、长句原子批处理写盘、表格全量追加填充（含表头保护与序号自增）。
    """
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
        参数：
        - selector: 'paragraph' / 'table' / 'all'
        - keyword_filter: 填入关键词短语。
        - window: 匹配点外延上下关联段数（默认 3 段）。
        """
        logger.info(f"   🔧 [Worker 视野] 查询结构 (selector='{selector}', kw='{keyword_filter}')")
        raw_text = _sync_call_async(officecli_query_structure_tool.coroutine, file_path=docx_temp_path, selector=selector)
        return _filter_dom_scope(str(raw_text), chapter_title, keyword_filter, window)

    @tool
    def officecli_write_slot_value(path: str, value: str) -> str:
        """
        [原位节点写盘工具] 对 Word 指定节点 Path 进行 100% 格式继承的原位值替换。
        """
        logger.info(f"   ✍️ [Worker 写盘] 写入节点 {path} -> {value}")
        return _sync_call_async(officecli_write_slot_value_tool.coroutine, file_path=docx_temp_path, path=path, value=value)

    @tool
    def officecli_batch_fill_sentence(updates_json_str: str) -> str:
        """
        [长句/段落原子批处理写盘工具] 在收集齐该章节长段落的所有字段后，一次性提交更新。
        参数 updates_json_str 格式：'[{"path": "/body/p[2]", "value": "公司名称：XXX..."}, ...]'
        """
        logger.info(f"   📝 [Worker 原子写盘] 提交长句批处理更新: {updates_json_str[:150]}...")
        return _sync_call_async(officecli_batch_fill_sentence_tool.coroutine, file_path=docx_temp_path, updates_json_str=updates_json_str)

    @tool
    def officecli_fill_table_rows(table_path: str, rows_json_str: str, auto_index: bool = True) -> str:
        """
        [表格全量追加填充工具] 批量填充表格行，自动保留 row[1] 表头不变，并在第一列自动生成 1..N 递增序号。
        参数 rows_json_str 格式：'[["张三", "项目经理"], ["李四", "架构师"]]'
        """
        logger.info(f"   📊 [Worker 表格写盘] 向表格 {table_path} 批量填充数据行")
        return _sync_call_async(
            officecli_fill_table_rows_tool.coroutine,
            file_path=docx_temp_path,
            table_path=table_path,
            rows_json_str=rows_json_str,
            auto_index=auto_index
        )

    @tool
    def officecli_insert_image(target_path: str, image_path: str, width_inches: float = 5.5, caption: str = "") -> str:
        """
        [资质证明与图片嵌入工具] 在 Word 指定节点 Path (如 '/body/p[12]' 或 '/body/tbl[1]/row[2]/cell[1]') 插入资质证明/证书图片。
        参数：
        - target_path: Word 中的物理 DOM 节点 Path
        - image_path: 资质证书图片的磁盘绝对路径 (可通过 query_company_qualification_tool 查库获取)
        - width_inches: 图片宽度 (默认 5.5 英寸)
        - caption: 图片说明图注 (可选，如 '营业执照')
        """
        logger.info(f"   🖼️ [Worker 图片写盘] 节点 {target_path} -> 嵌入图片 {image_path}")
        return officecli_insert_image_tool.func(
            file_path=docx_temp_path,
            target_path=target_path,
            image_path=image_path,
            width_inches=width_inches,
            caption=caption
        )

    from app.agents.tools.style_extractor_tool import extract_text_by_style
    worker_tools = list(db_tools) + [
        officecli_query_structure,
        officecli_write_slot_value,
        officecli_batch_fill_sentence,
        officecli_fill_table_rows,
        officecli_insert_image,
        get_full_chapter_text,
        search_bidding_document,
        extract_text_by_style,
    ]
    logger.info(f"   🛠️ [Worker 工具包] 组装完成: {len(db_tools)} DB工具 + 5 Office CLI 工具 + 2 RAG/全章检索工具 + 1 样式定向提取工具")
    return worker_tools



# ============================================================
# Worker Prompt — 直写 Word 与专项修复模式
# ============================================================

def build_worker_prompt(
    chapter_title: str,
    category: str,
    template_text: str,
    content_hint: str,
    document_id: str,
    extra_instructions: str = "",
    repair_instructions: str = "",
) -> tuple:
    """构建章节 Worker Agent 的 System Prompt 与 User Prompt（支持直写与专项修复）。

    :param extra_instructions: 用户自定义额外指令
    :param repair_instructions: Supervisor 下发的专项修复反馈指令
    """
    cat = (category or "needs_fill").lower().strip()

    system_prompt = f"""你是标书撰写专家，负责直接对 Word 标书文档的【{chapter_title}】章节进行信息检索与原位填盘操作。

【最高铁律 — 原文零改动零遗漏法则】
1. 🔒 **模板原文 100% 盲守**：绝对严禁删除、篡改、润色、删减或遗漏任何模板原文（包括前缀标签如“项目名称：”、“招标编号：”、“致：”、标点符号及授权声明等全部固定文本）！
2. 🎯 **仅精准替换占位符**：只针对模板中的下划线 `______`、括号 `( )`、`[待填]` 槽位填充检索到的真实数据，非占位符的原文必须 100% 原封不动完整保留！

【工作流规范 — 必须严格按顺序执行】
1. 🔍 **扫描识别**：使用 `officecli_query_structure(selector='all', keyword_filter='{chapter_title}')` 扫描本章节内的下划线 `______`、括号 `( )` 占位符或空白表格。
2. 🗄️ **多源检索与原文件整章全量阅读**：
   - 📖 **整章原文提炼 (地毯式对照盲守)**：针对需要地毯式对照原文件条款进行响应的章节（如《商务条款偏离表》、《技术偏离表》、《投标函及响应表》），**优先调用 `get_full_chapter_text(document_id, chapter_name)` 检索原文件中相关章节的 100% 完整段落原文**（例如 `get_full_chapter_text(document_id, "合同条款")` 或 `get_full_chapter_text(document_id, "商务条款")`），彻底消除信息截断盲区！
   - 🔀 **交叉章节检索强指引 (Cross-Chapter Retrieval)**：当填报任务涉及跨多个章节进行对比分析与交叉检索时（例如《商务条款偏离表》需要同时交叉检索“第三章 合同条款”、“第四章 项目需求商务条款”及“第六章 格式”），**必须分别多次调用 `get_full_chapter_text(document_id, chapter_name)` 获取相关各个章节的 100% 全量原文**，绝对严禁仅依靠单一章节或断章取义！
   - 🏢 **企业与报价 DB 直查与查无止步原则**：
     - 针对扫描到的具体字段，主动调用 DB 工具集（企业信息、资质库、人员库、业绩库、财务库等）检索真实数据。
     - 🖼️ **资质证书与资格证明文件自主检索与图片嵌入法则**：
       - 当处理【资格证明文件】、【资质证书】、【营业执照】或带有资质占位符（如 `[待手动补充资质证书: 营业执照]`）的章节与槽位时，**必须自主调用 `query_company_qualification_tool(cert_keyword)` 检索数据库中的匹配资质证书与磁盘图片绝对路径 (`local_image_path`)**。
       - 查找到有效资质证书图片后，**必须自主调用 `officecli_insert_image(target_path, image_path, width_inches=5.5, caption=...)` 工具，将资质证书图像原位嵌入到 Word 目标节点中**！
     - 🛑 **查无结果立刻止步**：若 DB 工具返回 "未找到..."、"尚未录入" 或空记录，**严禁换用类似关键词重复循环调库**！应当立即将该槽位标记或写为 "[待补充: <字段名>]"，并直接完成该句/表单写盘。
     - 🚫 **杜绝伪造假数据**：绝对严禁捏造假数据或伪造日期！写盘完成后必须立即输出总结表格并终止工具调用，绝对不能死循环！
   - 🎨 **文档精细样式感知与定向提取规约**：
     - 遇到需根据特定字体格式属性（如“参考第四章中斜体且带有下划线的文字”）响应时，文档中的斜体下划线文本已被转义为 `<span class="style-italic-underline"><u>*文本*</u></span>`。
     - 亦可直接调用 `extract_text_by_style(file_path, chapter_keyword, style_type="italic_underline")` 工具进行特定章节格式文本的定向提取！



3. ✍️ **一并写盘 (原子化长句 & 表格填写铁律 — 严禁假写)**：
   - 🚨 **必须显式调用写盘工具 (严禁只在总结中写"保持原文"或"已存在填位")**：
     - 针对扫描到的任何占位符槽位（如“项目名称：______”、“招标编号：______”、“投标单位（盖章）：______”、“日期：______”），**必须显式调用写盘工具 (`officecli_batch_fill_sentence` / `officecli_write_slot_value` / `officecli_fill_table_rows`)，将完整的新文本（标签+查得数据，如 `value="投标单位（盖章）：某某工程有限公司"`) 真正写入 Word 文件**！
     - ❌ **严重违规**：绝对禁止仅在回答中打嘴炮回复“保持原文下交”、“已存在填位”、“与已填内容吻合”而不调用任何 `officecli` 写入工具！如果不真正调用写盘工具，Word 文件中的空位下划线将永远无法被替换，会导致生成的标书封面和表格为空！
     - 只要本章节存在需填写/落盘的字段，**必须至少成功执行一次写盘工具**，将查得的真实数据（如项目名称、招标编号、投标单位全称、日期等）刷写入 Word 文档！
   - 🏷️ **前缀标签完整继承与真实数据替换法则 (防擦除与防空照抄铁律)**：
     - 若目标段落/槽位原文本包含字段属性名标签（例如 `"项目名称：______"` 或 `"招标编号：______"`），写盘提交的 `value` **必须完整保留前缀标签，并必须将下划线/空位替换为查得的数据**！
     - ❌ **严重错误写盘 1**：`value = "XXX项目名称"` （会导致 "项目名称：" 前缀标签被误抹除擦掉）；
     - ❌ **严重错误写盘 2**：`value = "招标编号：号 项目名称："` （未填入任何数据原样照抄模板，系严重违规！）；
     - ✅ **正确写盘**：`value = "招标编号：XXX-2026-PV-001 项目名称：某某光伏发电项目"`；
     - ✅ **正确写盘**：`value = "投标单位（盖章）：某某建设工程有限公司"`；
     - ✅ **正确写盘**：`value = "日期：2026年XX月XX日"`。
   - 🏢 **采购人 vs 招标代理机构 实体区分法则**：
     - 在授权委托书等公文格式中：
       - `致：_____` 填写 **招标代理机构全称**（如 "某某招标代理咨询有限公司"）；
       - `参加 _____ 组织的...` 必须填写 **采购人/招标人单位全称**（即项目业主/采购单位全称，如 "某某建设/业主有限公司"），**绝对严禁将代理机构名称错填为“参加...组织的”主语**！
   - 📝 **长段落/长句**：必须等收集齐该句子或段落所需的所有数据后，使用 `officecli_batch_fill_sentence(updates_json_str)` 或 `officecli_write_slot_value` 进行一次性原子更新。
   - 📊 **表格数据填写**：使用 `officecli_fill_table_rows(table_path, rows_json_str, auto_index=True)` 进行全量追加；
     - 🎯 **主表优先法则 (防止入口主表留空)**：
       - 当本章节作用域内探测到多个表格（如 `/body/tbl[1]`, `/body/tbl[2]`）时，**必须优先选择紧贴在章节大标题正下方、且包含目标表头字段（如"货物名称/项目名称/规格型号/单价/总价"）的第一个主表格（通常为 `/body/tbl[1]`）进行原位数据填充**！
       - 🚫 **严禁大面积留空主表**：绝对禁止跳过上方的空白主表格而将数据错填到下方的次要/附带表格 (`tbl[2]`) 中！
     - 🛡️ **表头保护**：跳过表格第一行 `row[1]`，严禁修改表头名；
     - 🔢 **序号自增**：第一列自动填入 `1, 2, 3...` 连续递增数字，绝对不能有缺号或 null；
     - 💯 **全量无遗漏**：检索出的所有符合条件的记录（如多位人员、多项资质）必须全量填入表格，严禁遗漏任何一行或一列。

【输出总结格式要求 — 必须包含 Markdown 表格】
在完成所有读写工具调用后，请给出一份操作总结，**必须在总结末尾输出如下格式的 Markdown 明细表格**：
| 序号 | DOM 节点路径 | 替换前模板原文 | 实际填入/扩写结果 | 写盘状态 |
- 第 3 列 (替换前模板原文)：填入替换前未修饰的原始模板文本（如 `"招标编号：______ 项目名称：______"` 或 `"投标单位（盖章）：______"`）；
- 第 4 列 (实际填入/扩写结果)：填入实际替换数据后的完整新文本（如 `"招标编号：XXX-2026-PV-001 项目名称：某某光伏发电项目"` 或 `"投标单位（盖章）：某某建设工程有限公司"`）。**严禁在第 4 列填写"保持原文下交"或无脑复制第 3 列！**"""

    if extra_instructions:
        system_prompt += f"""\n\n【📌 用户自定义指令】\n{extra_instructions}"""

    if repair_instructions:
        system_prompt += f"""\n\n【🚨 专项修复紧急指令 — Supervisor 质量审核反馈】
Supervisor 在上一轮审核中发现以下问题，请优先对该章节实施专项补救与重新写盘：
{repair_instructions}"""

    user_prompt = f"""【撰写任务】
- 文档 ID: {document_id}
- 章节标题: {chapter_title}
- 任务类别: {category}

【甲方原文模板】
{template_text or '（按招标要求智能撰写）'}

【填写说明】
{content_hint or '（无特殊说明）'}

请开启工具调取与写盘，完成【{chapter_title}】章节的智能撰写。"""

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
    logger.info(f"⚡ [Worker Direct-Fill] 启动撰写 Agent → [{chapter_title}] (类别: {cat})")
    if repair_instructions:
        logger.warning(f"🔧 [Worker 专项修复模式] 接收到 Supervisor 反馈指令: {repair_instructions[:100]}...")

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
        worker_tools = _build_worker_tools(docx_temp_path=docx_temp_path, chapter_title=chapter_title)
        system_prompt, user_prompt = build_worker_prompt(
            chapter_title=chapter_title, category=cat,
            template_text=template_text, content_hint=content_hint,
            document_id=document_id,
            extra_instructions=extra_instructions,
            repair_instructions=repair_instructions,
        )


        # [优化点1：零度确定性控制] 常规表单与表格清单填写必须无限强行死扣于 `temperature=0.0`；长文本限制于0.2
        target_temp = 0.0 if cat in ("needs_fill", "needs_data", "skip") else 0.2
        worker_llm = llm_service.get_llm(temperature=target_temp, json_mode=False)
        if not worker_llm:
            worker_llm = llm_service.raw_llm
        logger.info(f"❄️ [零温防偏锁定] Worker [{chapter_title}] ({cat}) → 分配无震动恒等模型 (temperature={target_temp})")

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
                if is_conn_err and attempt < max_retries:
                    backoff = attempt * 1.5
                    logger.warning(f"⚠️ [Worker 网络重试] [{chapter_title}] 第 {attempt} 次请求遇到 API 连接异常 ({err})，等待 {backoff:.1f}s 后自动重试...")
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

        # 1. 优先解析 Worker 输出的全量结构化提案列表或总结表格
        proposals = _parse_proposals(final_msg)
        if not proposals:
            # 容错提取：从 ReAct 工具调用参数中自动提取实际刷盘的提案明细
            for step in thought_steps:
                if step.get("type") == "thought" and step.get("tool_calls"):
                    for tc in step["tool_calls"]:
                        tc_name = tc.get("name", "")
                        tc_args = tc.get("args", {})
                        if "batch_fill" in tc_name or "write_slot" in tc_name:
                            val_str = str(tc_args.get("updates_json_str") or tc_args.get("value") or tc_args)
                            proposals.append({
                                "path": tc_args.get("slot_path") or tc_args.get("path") or f"DOM-{chapter_title[:10]}",
                                "original_context": "模板占位槽位",
                                "proposed_text": val_str[:150],
                                "status": "success"
                            })
                        elif "fill_table" in tc_name:
                            rows_str = str(tc_args.get("rows_json_str") or tc_args)
                            proposals.append({
                                "path": tc_args.get("table_path") or f"Table-{chapter_title[:10]}",
                                "original_context": "表格模板行",
                                "proposed_text": rows_str[:150],
                                "status": "success"
                            })
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
            f"✅ [Worker Agent 完成] [{chapter_title}] | 耗时: {int((t_end - t_start) * 1000)}ms | "
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
        logger.error(f"❌ [Worker] [{chapter_title}] 失败: {e}")
        return {
            "chapter_title": chapter_title, "mapping_hint": mapping_hint,
            "category": cat, "status": "failed", "proposals": [],
            "error": str(e)[:500],
        }


def _repair_json_unescaped_quotes(json_str: str) -> str:
    """自动对 JSON 字符串值中未经转义的半角双引号进行容错替换"""
    import re
    def fix_field_val(m):
        prefix = m.group(1)   # `"reasoning": "`
        content = m.group(2)  # `原文"招标编号..."`
        suffix = m.group(3)   # `"`
        fixed_content = content.replace('"', '”')
        return f'{prefix}{fixed_content}{suffix}'
    pattern = r'("(?:path|original_context|source_data|source_tool|proposed_text|reasoning|chapter_title|mapping_hint)"\s*:\s*")([\s\S]*?)("\s*[,\}])'
    return re.sub(pattern, fix_field_val, json_str)


def _parse_proposals(raw_text: str) -> List[Dict[str, Any]]:
    """从 Worker 的最终回复中提取 JSON 提案列表（包含多重智能容错与对象恢复机制）"""
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
    # 策略4: 修复常见 JSON 错误后重试（尾部多余逗号、非法未转义双引号修补）
    match = re.search(r'\[\s*\{[\s\S]*?\}\s*\]', cleaned, re.DOTALL)
    if match:
        raw_json_array = match.group(0)
        try:
            fixed = re.sub(r',\s*\]', ']', raw_json_array)  # 去尾部逗号
            fixed = re.sub(r',\s*\}', '}', fixed)
            return _json.loads(fixed)
        except Exception:
            pass
        # 针对字符串内部未转义双引号实施智能修复
        try:
            repaired = _repair_json_unescaped_quotes(raw_json_array)
            repaired = re.sub(r',\s*\]', ']', repaired)
            repaired = re.sub(r',\s*\}', '}', repaired)
            data = _json.loads(repaired)
            if isinstance(data, list):
                logger.info(f"   💡 [Worker 自动修复] 成功修补字符串内部未转义双引号，恢复 {len(data)} 条提案")
                return data
        except Exception:
            pass

    # 策略5: 对象级逐项恢复机制（Chunk-by-chunk Object Recovery）
    # 当整组数组解析语法崩溃时，按单独的 {...} 提案对象正则扫描抓取
    obj_matches = re.finditer(r'\{\s*"path"\s*:[\s\S]*?\}', raw_text)
    recovered = []
    for m in obj_matches:
        candidate = m.group(0)
        try:
            item = _json.loads(candidate)
            if isinstance(item, dict) and "path" in item:
                recovered.append(item)
                continue
        except Exception:
            pass
        try:
            repaired_cand = _repair_json_unescaped_quotes(candidate)
            item = _json.loads(repaired_cand)
            if isinstance(item, dict) and "path" in item:
                recovered.append(item)
        except Exception:
            pass

    if recovered:
        logger.info(f"   🛡️ [Worker 对象拯救机制] 从语法崩溃的回复中逐个拯救恢复出 {len(recovered)} 条合法提案！")
        return recovered

    # 策略6: 从 Markdown 表格行提取提案明细
    if "|" in raw_text:
        table_rows = []
        for line in raw_text.split("\n"):
            l_str = line.strip()
            if not l_str.startswith("|") or "---" in l_str or "序号" in l_str or "DOM 节点" in l_str or "替换前" in l_str:
                continue
            cells = [c.strip() for c in l_str.split("|") if c.strip()]
            if len(cells) >= 3:
                path_val = cells[1] if len(cells) >= 2 else cells[0]
                orig_val = cells[2] if len(cells) >= 3 else cells[1]
                prop_val = cells[3] if len(cells) >= 4 else cells[2]
                table_rows.append({
                    "path": path_val,
                    "original_context": orig_val,
                    "proposed_text": prop_val,
                    "status": "success"
                })
        if table_rows:
            logger.info(f"   📊 [Worker 总结表格解析] 从 Markdown 总结表格中恢复提炼出 {len(table_rows)} 条写盘明细")
            return table_rows

    logger.warning(f"   ⚠️ [Worker] 无法解析提案 JSON ({len(raw_text)} 字符):\n{raw_text[:500]}...")
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
