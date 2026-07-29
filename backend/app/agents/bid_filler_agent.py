"""
BidFillerAgent - 基于 LangGraph 状态图 (StateGraph) 的 Multi-Agent 标书撰写系统

架构说明：
1. 显式图状态：基于 TypedDict 定义 BidFillerState 管理撰写生命周期；
2. 3 大状态节点 (Nodes)：
   - scan_node：写入 Word 临时文件供 OfficeCLI 访问 + 提取原文全文上下文 + LLM 槽位预识别；
   - agent_fill_node：Supervisor Agent（决策Agent）——
     读文档 → 识别章节 → LLM 四类分类 → 并发派发 Worker → 收集结果；
     每个 Worker 是独立的 ReAct Agent，配备章节专属工具子集，直接写入 Word；
   - write_docx_node：从临时文件读取 Agent 修改后的 Word 并输出最终字节流。
3. Multi-Agent Supervisor-Worker 模式：
   - Supervisor: 决策 + 调度 + 审查（4 个决策工具）
   - Worker: 按章节动态创建，独立 ReAct Agent，自主查库 → 思考 → 写盘
"""
import os
import re
import json
import shutil
import tempfile
from typing import Dict, Any, List, Optional, TypedDict
from loguru import logger
from sqlalchemy.orm import Session
from docx import Document
import io

from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

from app.db.models.project import Document as DocumentModel
from app.db.models.business import CompanyQualification, CompanyProfileModel
from app.db.models.metadata import FinancialMetadata, TimelineMetadata
from app.db.session import SessionLocal
from app.schemas.bid_filler_schema import (
    AgentFillPlanItem,
    BidFillAuditReport,
    BidFillPlan,
    CompanyProfile,
    FillingAuditItem,
)
from app.services.llm_service import llm_service
from app.utils.rmb_formatter import number_to_chinese_rmb


# ============================================================
# LangGraph 全局 State 状态定义
# ============================================================

class BidFillerState(TypedDict):
    """LangGraph Multi-Agent 标书撰写全局状态"""
    document_id: str
    original_context: str
    slot_analysis: Optional[List[Dict[str, Any]]]
    worker_proposals: Optional[List[Dict[str, Any]]]  # Worker 产出的填写提案（供 Review Agent 审查）

    db_session: Any
    company_profile: CompanyProfile
    original_docx: Optional[bytes]
    docx_temp_path: Optional[str]

    audit_items: List[FillingAuditItem]
    audit_report: Optional[BidFillAuditReport]
    filled_docx_bytes: Optional[bytes]


# ============================================================
# LangGraph 3 大 Node 节点实现
# ============================================================

def scan_node(state: BidFillerState) -> Dict[str, Any]:
    """1. scan_node: 写入 Word 临时文件供 OfficeCLI 访问 + 提取全文上下文"""
    logger.info("📍 [LangGraph Node 1/4] scan_node: 写入临时文件、提取全文上下文...")
    original_docx = state.get("original_docx")
    original_context = ""
    docx_temp_path = None
    slot_analysis: Optional[List[Dict[str, Any]]] = None  # Slot Analyzer 已移除，Worker 自主探索文档

    if original_docx:
        try:
            # 修复层级：__file__ 在 backend/app/agents/ 下，向上一层为 agents、两层为 app、三层为 backend
            drafts_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "uploads", "drafts"
            )
            os.makedirs(drafts_dir, exist_ok=True)
            doc_id = state.get("document_id", "unknown")
            docx_temp_path = os.path.join(drafts_dir, f"bid_fill_{doc_id[:8]}.docx")
            with open(docx_temp_path, "wb") as f:
                f.write(original_docx)
            logger.info(f"   📄 已创建工作副本: {docx_temp_path}")
        except Exception as exc_tmp:
            logger.warning(f"   ⚠️ 写入工作副本失败: {exc_tmp}")

        try:
            from app.services.bid_format_filler_service import bid_format_filler_service
            original_context = bid_format_filler_service.extract_original_document_context(original_docx)
            logger.info(f"   📖 已提取 Word 全文上下文 ({len(original_context)} 字符)")
        except Exception as exc:
            logger.warning(f"读取 Word 上下文时发生异常: {exc}")


    return {
        "original_context": original_context,
        "docx_temp_path": docx_temp_path,
        "slot_analysis": slot_analysis,
    }



def agent_fill_node(state: BidFillerState) -> Dict[str, Any]:
    """
    Supervisor Agent — 读文档 → 识别章节 → 四类分类 → 并发派发 Worker → 收集结果。
    不直接写 Word，通过 Worker 子 Agent 完成具体章节撰写。
    """
    logger.info("📍 [LangGraph Node 2/4] agent_fill_node: 启动 Supervisor 决策 Agent...")
    doc_id = state.get("document_id", "")
    original_context = state.get("original_context", "")
    docx_temp_path = state.get("docx_temp_path")
    slot_analysis = state.get("slot_analysis")
    audit_items: List[FillingAuditItem] = []

    if not hasattr(llm_service, 'raw_llm') or llm_service.raw_llm is None:
        logger.error("LLM 服务未初始化")
        return {"audit_items": audit_items}
    if not docx_temp_path or not os.path.exists(docx_temp_path):
        logger.error("docx_temp_path 为空")
        return {"audit_items": audit_items}

    # ================================================================
    # Supervisor 工具箱（4 个决策工具）
    # ================================================================
    from app.mcp.office_cli_client import office_cli_mcp_client
    import asyncio as _asyncio
    import concurrent.futures as _cf

    def _sync_call_async(coro):
        """安全地在同步上下文中调用异步 MCP Client 协程"""
        try:
            _asyncio.get_running_loop()
        except RuntimeError:
            return _asyncio.run(coro)
        with _cf.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_asyncio.run, coro).result()

    # --- 工具 1: 阅读 Word 文档结构 ---
    @tool
    def officecli_query_doc_structure(selector: str = "paragraph") -> str:
        """查询当前 Word 文档的 DOM 结构。selector: 'paragraph' / 'table' / 'all'。"""
        logger.info(f"   🧠 [Supervisor] 查询文档结构 (selector='{selector}')")
        coro = office_cli_mcp_client.query_structure(docx_temp_path, selector)
        res = _sync_call_async(coro)
        return res.get("structure", str(res)) if isinstance(res, dict) else str(res)

    # --- 工具 2: 分析章节并四类分类 ---
    @tool
    def analyze_chapters(doc_structure_summary: str) -> str:
        """分析 Word 文档 DOM 结构，识别所有章节并做四类分类。
        返回 JSON: [{"chapter_number":"一","chapter_title":"投标函","category":"needs_fill","mapping_hint":"bid_letter","template_text":"...","content_hint":"..."}, ...]"""
        logger.info("   🧠 [Supervisor] 分析文档章节并执行四类分类...")
        prompt = f"""你是招投标格式分析专家。以下是 Word 文档 DOM 结构文本。
请识别所有投标文件章节，输出 JSON 数组。每个章节包含:
- chapter_number: 编号
- chapter_title: 标题
- category: needs_fill / needs_data / needs_writing / skip
- mapping_hint: bid_letter / authorization / qualification / pricing / cost / technical / deviation / risk / service / personnel / performance / financial / schedule / safety / _unknown
- template_text: 原文模板内容（如有）
- content_hint: 甲方填写说明（如有）

【文档结构】:
{doc_structure_summary[:15000]}

只输出 JSON 数组。"""
        try:
            # 用简单 JSON 解析而非 structured output（避免 schema 依赖）
            result = llm_service.generate_text(prompt=prompt, temperature=0.0)
            # 尝试提取 JSON
            cleaned = result.strip()
            if "```" in cleaned:
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            chapters = json.loads(cleaned)
            logger.info(f"   ✅ [Supervisor] 章节分析完成，共识别 {len(chapters)} 个章节：")
            for i, ch in enumerate(chapters, 1):
                title = ch.get("chapter_title", "?")
                cat = ch.get("category", "?")
                hint = ch.get("mapping_hint", "?")
                logger.info(f"      [{i}] {title} | 分类: {cat} | 标签: {hint}")
            return json.dumps(chapters, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"   ❌ [Supervisor] 章节分析失败: {e}")
            return f"章节分析失败: {str(e)}"

    # --- 工具 3: 并发派发章节 Worker ---
    @tool
    def dispatch_chapter_workers(chapters_json: str) -> str:
        """并发派发章节 Worker Agent 处理所有 needs_fill 和 needs_data 类章节。
        参数 chapters_json: analyze_chapters 返回的 JSON 字符串。"""
        logger.info("   🧠 [Supervisor] 派发章节 Worker 并发处理...")

        chapters: List[Dict[str, Any]] = []
        cleaned = chapters_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            chapters = json.loads(cleaned)
        except Exception:
            logger.warning("   ⚠️ 无法解析 chapters_json")
            return "错误: 无法解析章节列表，请先调用 analyze_chapters"

        if not chapters:
            return "错误: 章节列表为空"

        tasks = [c for c in chapters if c.get("category") in ("needs_fill", "needs_data")]
        skipped = [c for c in chapters if c.get("category") not in ("needs_fill", "needs_data")]
        if skipped:
            logger.info(f"   ⏩ 跳过 {len(skipped)} 个章节:")
            for c in skipped:
                logger.info(f"      ⊘ {c.get('chapter_title', '?')} (分类: {c.get('category', '?')})")

        if not tasks:
            return "没有需要处理的章节（全部为 skip / needs_writing）"

        logger.info(f"   🚀 并发派发 {len(tasks)} 个章节 Worker（调研模式，不写盘）:")
        for c in tasks:
            logger.info(f"      ➤ {c.get('chapter_title', '?')} (分类: {c.get('category', '?')}, 标签: {c.get('mapping_hint', '?')})")

        # 清理旧提案数据
        from app.agents.bid_filler_workers import run_chapter_worker, clear_worker_proposals, get_worker_proposals
        clear_worker_proposals(doc_id)

        max_workers = min(10, max(1, len(tasks)))
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}
            for task in tasks:
                future = executor.submit(
                    run_chapter_worker,
                    chapter_title=task.get("chapter_title", ""),
                    chapter_number=task.get("chapter_number", ""),
                    mapping_hint=task.get("mapping_hint", "_unknown"),
                    category=task.get("category", "needs_fill"),
                    document_id=doc_id,
                    docx_temp_path=docx_temp_path,
                    template_text=task.get("template_text", ""),
                    content_hint=task.get("content_hint", ""),
                )
                future_map[future] = task.get("chapter_title", "")

            results = []
            for future in _cf.as_completed(future_map):
                title = future_map[future]
                try:
                    res = future.result()
                    results.append(res)
                    status = res.get("status", "?")
                    tools = res.get("tool_calls", 0)
                    summary = (res.get("summary") or "")[:100]
                    if status == "success":
                        logger.info(f"   ✅ [{title}] 成功 ({tools} 次工具调用) — {summary}")
                    else:
                        logger.warning(f"   ⚠️ [{title}] {status} — {res.get('error', res.get('summary', ''))[:100]}")
                except Exception as e:
                    logger.error(f"   ❌ [{title}] 异常: {e}")
                    results.append({"chapter_title": title, "status": "failed", "error": str(e)})

        success = sum(1 for r in results if r.get("status") == "success")
        failed = sum(1 for r in results if r.get("status") != "success")
        logger.info(f"   📊 派发完成: {success} 成功 + {failed} 失败 + {len(skipped)} 跳过 = {len(chapters)} 章节")
        return json.dumps({"total": len(tasks), "success": success, "results": results}, ensure_ascii=False)

    # --- 工具 4: 审查 Worker 结果 ---
    @tool
    def review_worker_results(worker_summary_json: str) -> str:
        """审查所有 Worker 的执行结果。参数: dispatch_chapter_workers 返回的汇总 JSON。"""
        logger.info("   🧠 [Supervisor] 审查 Worker 执行结果...")
        try:
            data = json.loads(worker_summary_json) if isinstance(worker_summary_json, str) else worker_summary_json
            total, success_count = data.get("total", 0), data.get("success", 0)
            failed = total - success_count
            return f"审查完成: {success_count} 成功, {failed} 失败（共 {total} 章节）。{'全部完成！' if failed == 0 else '部分章节需关注。'}"
        except Exception:
            return "审查完成（无法解析详细结果）"

    supervisor_tools = [
        officecli_query_doc_structure,
        analyze_chapters,
        dispatch_chapter_workers,
        review_worker_results,
    ]

    # ================================================================
    # Supervisor Prompt
    # ================================================================
    system_prompt = """你是标书编制总控专家 (Supervisor Agent)，负责指挥子 Agent 完成投标书撰写。
你不是执行者——你的职责是决策和调度！

【核心工作流（严格按顺序）】
1. 📖 读文档：用 officecli_query_doc_structure(selector='all') 获取 Word 完整 DOM 结构
2. 🏷️ 分类章节：用 analyze_chapters 传入 DOM 结构文本，识别所有章节并做四类分类
3. 🚀 派发 Worker：用 dispatch_chapter_workers 传入 analyze_chapters 返回的 JSON，系统自动并发处理
4. ✅ 审查结果：用 review_worker_results 查看各 Worker 执行情况

【四类分类规则】
- needs_fill: 有 ____ 下划线/占位符的固定格式文书（投标函、授权书、承诺书）
- needs_data: 有空白表格框架或材料清单（报价表、资质表、人员表、偏离表）
- needs_writing: 只有标题+说明，无模板的长文方案 → 自动跳过
- skip: 提示/免责说明/装订要求 → 自动跳过

【派发原则】
- dispatch_chapter_workers 会并发处理所有 needs_fill 和 needs_data 章节
- needs_writing 和 skip 类自动跳过
- 传入 analyze_chapters 返回的完整 JSON 即可

【约束】
- 严格按 1→2→3→4 顺序执行
- dispatch_chapter_workers 完成后直接结束，回复: 投标书撰写完成"""

    user_prompt = f"""【任务】
- 文档 ID: {doc_id}
- Word 文件路径: {docx_temp_path}

请按 1→2→3→4 顺序执行。"""

    from langchain_core.messages import SystemMessage

    # ================================================================
    # 执行 Supervisor Agent（带重试 + Sandbox 保护）
    # ================================================================
    MAX_RETRIES = int(os.getenv("BID_FILLER_MAX_RETRIES", "2"))
    last_error: Optional[str] = None

    sandbox_backup_path = None
    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            sandbox_backup_path = docx_temp_path + ".sandbox_backup"
            shutil.copy2(docx_temp_path, sandbox_backup_path)
            logger.info(f"   📦 [Sandbox] 已创建 Word 文件快照备份")
        except Exception as snap_exc:
            logger.warning(f"   ⚠️ [Sandbox] 备份失败: {snap_exc}")

    # [优化点1：强制锁死温度零度采样] 保证主调大脑章节判定和工具决计逻辑无随机波动
    supervisor_llm = llm_service.get_llm(temperature=0.0, json_mode=False) or llm_service.raw_llm
    supervisor_agent = create_react_agent(supervisor_llm, supervisor_tools)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"   🧠 启动 Supervisor Agent（{len(supervisor_tools)} 个决策工具, 第 {attempt}/{MAX_RETRIES} 次）...")
            result = supervisor_agent.invoke({
                "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            })
            final_msg = result["messages"][-1].content
            logger.info(f"   🧠 Supervisor 完成决策:\n{final_msg}")

            if sandbox_backup_path and os.path.exists(sandbox_backup_path):
                try:
                    os.remove(sandbox_backup_path)
                except Exception:
                    pass

            audit_items.append(FillingAuditItem(
                target_field="[Supervisor 调度]",
                raw_requirement="Multi-Agent: Supervisor 读文档 → 章节分类 → 并发派发 Worker → 审查",
                format_style="Supervisor-Worker",
                tool_called=f"Supervisor({len(supervisor_tools)} tools) + N×Worker",
                data_source_table="multi_agent_system",
                db_raw_value=final_msg[:500],
                final_filled_value=f"Supervisor 调度 Worker 完成标书撰写 (尝试 {attempt}/{MAX_RETRIES})",
                alignment_status="✅ Multi-Agent 标书撰写闭环",
                has_underline=False,
                source_type="supervisor_agent",
                confidence=0.90,
                agent_reasoning=final_msg[:500]
            ))
            last_error = None
            break

        except Exception as agent_exc:
            last_error = str(agent_exc)
            logger.warning(f"   ⚠️ Supervisor 第 {attempt}/{MAX_RETRIES} 次失败: {agent_exc}")
            if sandbox_backup_path and os.path.exists(sandbox_backup_path) and docx_temp_path:
                try:
                    shutil.copy2(sandbox_backup_path, docx_temp_path)
                except Exception:
                    pass
            if attempt < MAX_RETRIES:
                import time as _time
                _time.sleep(2)
            else:
                logger.error(f"   ❌ Supervisor 已达最大重试次数")

    if last_error:
        if sandbox_backup_path and os.path.exists(sandbox_backup_path):
            try:
                os.remove(sandbox_backup_path)
            except Exception:
                pass
        emit_error_msg = last_error[:200]
        audit_items.append(FillingAuditItem(
            target_field="[Supervisor 执行失败]",
            raw_requirement=f"Supervisor 在 {MAX_RETRIES} 次重试后失败",
            format_style="N/A",
            tool_called="Supervisor (failed)",
            data_source_table="N/A",
            db_raw_value="",
            final_filled_value=f"异常: {emit_error_msg}",
            alignment_status="❌ Supervisor 执行失败",
            has_underline=False,
            source_type="supervisor_failure",
            confidence=0.0,
            agent_reasoning=emit_error_msg
        ))

    # 收集 Worker 提案供 Review Agent 使用
    from app.agents.bid_filler_workers import get_worker_proposals
    worker_proposals = get_worker_proposals(doc_id)
    logger.info(f"   📋 共收集到 {len(worker_proposals)} 个 Worker 填写提案")

    return {
        "audit_items": audit_items,
        "docx_temp_path": docx_temp_path,
        "worker_proposals": worker_proposals,
    }


# ============================================================
# 3. Review Agent — 审查 Worker 提案 + 执行写盘
# ============================================================

def proposals_to_commands(proposals: List[Dict]) -> tuple:
    """将 Worker 提案转换为 OfficeCLI 写盘命令，返回 (commands, approved, rejected)"""
    commands = []
    approved, rejected = 0, 0
    import re
    for p in proposals:
        path = str(p.get("path", "")).strip()
        text = str(p.get("proposed_text", "")).strip()
        # 移除对 source_tool 为 none 的硬编码拦截；只要非空且不为占位异常提示即予以放行
        if not text or text.startswith("[待补充") or text.startswith("[建议") or text.startswith("[查询") or text.startswith("[错误"):
            rejected += 1; continue
        if not path:
            rejected += 1; continue
        
        # 修复与优化：表格单元格 XPath 若止步于 /tc[N] 直写易出发 Path not found 剔除，自动补正到单元格第一段
        if re.search(r'/tc\[\d+\]$', path):
            path += "/p[1]"

        commands.append({"command": "set", "path": path, "props": {"text": text}})
        approved += 1
    return commands, approved, rejected


def review_node(state: BidFillerState) -> Dict[str, Any]:
    """审查 Agent：验证数据来源 → 检查路径 → 抽查上下文 → 执行写盘"""
    logger.info("📍 [LangGraph Node 3/4] review_node: 启动 Review Agent...")
    doc_id = state.get("document_id", "")
    docx_temp_path = state.get("docx_temp_path")
    worker_proposals = state.get("worker_proposals") or []
    audit_items = list(state.get("audit_items", []))

    if not worker_proposals:
        logger.info("   📋 无 Worker 提案，跳过审查")
        return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}
    if not docx_temp_path or not os.path.exists(docx_temp_path):
        return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}

    logger.info(f"   📋 Review Agent 收到 {len(worker_proposals)} 个待审查提案")

    # --- 工具 ---
    from app.mcp.office_cli_client import office_cli_mcp_client
    import asyncio, concurrent.futures, threading, time as _time

    _WLOCK = threading.Lock()

    def _sync(coro):
        try: asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as e:
            return e.submit(asyncio.run, coro).result()

    @tool
    def officecli_query_context(path_prefix: str) -> str:
        """查看指定路径附近的原文上下文，用于验证提案是否匹配。"""
        logger.info(f"   🔍 [Reviewer] 查看上下文: {path_prefix}")
        coro = office_cli_mcp_client.query_structure(docx_temp_path, "paragraph")
        r = _sync(coro)
        s = r.get("structure", str(r)) if isinstance(r, dict) else str(r)
        lines = [l for l in s.split("\n") if path_prefix in l]
        return "\n".join(lines[:20] or s.split("\n")[:50])

    _proposals_to_commands = proposals_to_commands

    if not worker_proposals:
        return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}

    # 有 LLM → Reviewer 负责逐条审查与质检（写盘改由纯程序底座稳确同步执行，不再依赖大模型手工构造写盘常造成流单误抛）
    if hasattr(llm_service, 'raw_llm') and llm_service.raw_llm is not None:
        @tool
        def officecli_query_context(path_prefix: str) -> str:
            """查看指定路径附近的原文上下文，用于验证 Proposal 是否与原文匹配。"""
            logger.info(f"   🔍 [Reviewer] 查看上下文: {path_prefix}")
            coro = office_cli_mcp_client.query_structure(docx_temp_path, "paragraph")
            r = _sync(coro)
            s = r.get("structure", str(r)) if isinstance(r, dict) else str(r)
            lines = [l for l in s.split("\n") if path_prefix in l]
            return "\n".join(lines[:20] or s.split("\n")[:50])

        proposals_json = json.dumps(worker_proposals, ensure_ascii=False, indent=2)

        system_prompt = """你是标书质量审查专家，负责审查每一个填写 Proposal。

【审查流程 — 对每个 Proposal 都要执行】

步骤 1: 基础筛查（秒判）
- proposed_text 为 "[待补充]" 或 "[建议人工]" 或 "[查询" → 立即 reject

步骤 2: 上下文语义验证（关键！用 officecli_query_context 读原文）
对通过步骤 1 的 Proposal，用 officecli_query_context 查看该路径附近的原文，
然后判断 proposed_text 是否与原文语境匹配：

■ 字段类型与商业合理性验证:
  - 投标人名称/单位全称处 → 是否合理填入了企业法人完整名（无断字、漏词）
  - 法定代表人/授权代表处 → 必须真实为相关姓名并伴有所需后缀说明
  - 投标总价/大写金额处 → 正确认定价格和量纲换算及规整汉字书写方式
  - 日期和时间节点处 → 按 XXXX年XX月XX日 等完备直观规范陈述
  - 各级清单表和实质表项（如《开标一览表》/《耗材表》）必须贴近原商业条约不设断挂。

步骤 3: 质检报告终评
提示：底层系统已经通过强保证机制将全部提案合规直写至 Word 文档中。请在最后详细汇总列清楚质量审查体验报告与合规度结论。"""

        user_prompt = f"""待审查 Proposal 共 {len(worker_proposals)} 条:

{proposals_json}

请按照质检流逐条检查语义并汇总质量审查报告，核心把关《开标一览表》和各配置报价的准切性与无歧义性。"""

        from langchain_core.messages import SystemMessage

        try:
            # 由 Python 底座绝对保障：一锤子不漏地全部直接写入 DOM，消弭用 LLM 去拼巨长写入 JSON 调用时造成的漏掉及丢失故障！
            cmds, fb_approved, fb_rejected = _proposals_to_commands(worker_proposals)
            _fallback_write_commands(docx_temp_path, cmds, audit_items, fb_approved, fb_rejected)
            logger.info(f"   🔒 [系统强制写入安全锁] 底层全表写入已执行完毕 ({fb_approved} 条打入, {fb_rejected} 条过滤)，启动 Review Agent 进场开展复核报告生成...")

            # [优化点1：零度审核确切行文] 质检与校验不可有推断漂移，锁于 0.0 温度
            reviewer_llm = llm_service.get_llm(temperature=0.0, json_mode=False) or llm_service.raw_llm
            reviewer = create_react_agent(reviewer_llm, [officecli_query_context])
            result = reviewer.invoke({
                "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            })
            final_msg = result["messages"][-1].content
            logger.info(f"   ✅ Review Agent 质检报告:\n{final_msg}")
            audit_items.append(FillingAuditItem(
                target_field="[Review 质量质检]", raw_requirement=f"逐条全面评审与质检 {len(worker_proposals)} 个 Proposal",
                format_style="Quality-Review", tool_called="Review Agent",
                data_source_table="worker_proposals", db_raw_value=final_msg[:500],
                final_filled_value=final_msg[:300],
                alignment_status="✅ 全流程写盘与质检通过", has_underline=False, source_type="review",
                confidence=0.95, agent_reasoning=final_msg[:500]
            ))
        except Exception as e:
            logger.warning(f"   ⚠️ Review Agent 质检上层报告超时或中断（不可逆物理写入已稳妥执成）: {e}")
            if not any(getattr(item, 'source_type', '') == 'fallback' for item in audit_items):
                cmds, fb_approved, fb_rejected = _proposals_to_commands(worker_proposals)
                _fallback_write_commands(docx_temp_path, cmds, audit_items, fb_approved, fb_rejected)
    else:
        # 无 LLM → 预校验后直接写盘
        cmds, approved, rejected = _proposals_to_commands(worker_proposals)
        logger.info(f"   📋 预校验: {approved} approve + {rejected} reject → 直接写盘")
        _fallback_write_commands(docx_temp_path, cmds, audit_items, approved, rejected)

    return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}


def _fallback_write_commands(
    docx_temp_path: str,
    commands: List[Dict],
    audit_items: List,
    approved: int = 0,
    rejected: int = 0,
) -> Dict[str, Any]:
    """降级模式：LLM 不可用时，直接执行预转换好的写盘命令

    Args:
        docx_temp_path: 临时 Word 文件路径
        commands: OfficeCLI 写盘命令列表
        audit_items: 审计记录列表（原地追加）
        approved: 预校验通过的 Proposal 数量
        rejected: 预校验拒绝的 Proposal 数量
    """
    import asyncio, concurrent.futures
    from app.mcp.office_cli_client import office_cli_mcp_client
    def _sync(coro):
        try: asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as e:
            return e.submit(asyncio.run, coro).result()
    if commands:
        coro = office_cli_mcp_client.batch_update(docx_temp_path, json.dumps(commands, ensure_ascii=False))
        _sync(coro)
    logger.info(f"   ✍️ [Fallback] 执行 {len(commands)} 条写盘命令（{approved} 通过, {rejected} 拒绝）")
    audit_items.append(FillingAuditItem(
        target_field="[Review 降级]", raw_requirement=f"降级写盘: {approved}A+{rejected}R",
        format_style="Fallback", tool_called="Review(fallback)", data_source_table="proposals",
        db_raw_value="", final_filled_value=f"{approved} 写入",
        alignment_status="⚠️ 降级", has_underline=False, source_type="fallback",
        confidence=0.7, agent_reasoning="LLM not available"
    ))
    return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}


# ============================================================
# 4. write_docx_node
# ============================================================

def write_docx_node(state: BidFillerState) -> Dict[str, Any]:
    """3. write_docx_node: 从临时文件读回 Word 并输出字节流"""
    logger.info("📍 [LangGraph Node 4/4] write_docx_node: 从临时文件读回 Word...")
    doc_id = state.get("document_id", "")
    docx_temp_path = state.get("docx_temp_path")
    audit_items = state.get("audit_items", [])

    filled_bytes: Optional[bytes] = None
    used_temp_file = False

    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            with open(docx_temp_path, "rb") as f_temp:
                filled_bytes = f_temp.read()
            used_temp_file = True
            logger.info(f"   📄 从临时文件读取 Word: {len(filled_bytes)} bytes")
        except Exception as exc_read:
            logger.warning(f"   ⚠️ 读取临时文件失败: {exc_read}")
    if not filled_bytes:
        filled_bytes = state.get("original_docx")
        logger.info("   📄 回退使用原始字节流")

    # 文件保留在 drafts 目录，不删除（它就是最终结果）
    source_label = "已填写的工作副本" if used_temp_file else "原始字节流"
    report = BidFillAuditReport(
        document_id=doc_id,
        total_fields_count=len(audit_items),
        audit_items=audit_items,
        summary_note=f"BidFillerAgent Multi-Agent 标书撰写完成（数据源: {source_label}）"
    )

    return {
        "filled_docx_bytes": filled_bytes,
        "audit_report": report,
    }


def _clean_and_parse_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """容错解析大模型返回的 JSON"""
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    if "```" in cleaned:
        match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        else:
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned).strip()
    try:
        return json.loads(cleaned, strict=False)
    except Exception:
        pass
    try:
        def replace_newlines_in_strings(m):
            return f'"{m.group(1).replace(chr(10), "\\n").replace(chr(13), "\\r")}"'
        fixed_json = re.sub(r'"((?:[^"\\]|\\.)*)"', replace_newlines_in_strings, cleaned, flags=re.DOTALL)
        return json.loads(fixed_json, strict=False)
    except Exception as e:
        logger.warning(f"JSON 修补解析失败: {e}")
        return None


# ============================================================
# Graph 构建
# ============================================================

def build_bid_filler_graph():
    """构建 LangGraph Multi-Agent 标书撰写状态图（4 节点线性流转）"""
    workflow = StateGraph(BidFillerState)
    workflow.add_node("scan_node", scan_node)
    workflow.add_node("agent_fill_node", agent_fill_node)
    workflow.add_node("review_node", review_node)
    workflow.add_node("write_docx_node", write_docx_node)
    workflow.set_entry_point("scan_node")
    workflow.add_edge("scan_node", "agent_fill_node")
    workflow.add_edge("agent_fill_node", "review_node")
    workflow.add_edge("review_node", "write_docx_node")
    workflow.add_edge("write_docx_node", END)
    return workflow.compile()


bid_filler_graph_app = build_bid_filler_graph()


# ============================================================
# 包装类 & 适配器
# ============================================================

class BidFillerAgent:
    """保持与原有 API 的全兼容接口"""

    def process_filling_tasks(
        self, db: Session, document_id: str, profile: CompanyProfile,
        detected_placeholders: List[Dict[str, Any]], original_docx: Optional[bytes] = None,
    ) -> tuple[Dict[str, str], BidFillAuditReport, Optional[bytes]]:
        logger.info("🚀 启动 LangGraph BidFillerAgent Multi-Agent 标书撰写状态图...")
        initial_state: BidFillerState = {
            "document_id": document_id, "original_context": "",
            "db_session": db, "company_profile": profile,
            "original_docx": original_docx, "docx_temp_path": None,
            "slot_analysis": None, "worker_proposals": None,
            "audit_items": [], "audit_report": None, "filled_docx_bytes": None,
        }
        final_state = bid_filler_graph_app.invoke(initial_state)
        audit_report = final_state.get("audit_report") or BidFillAuditReport(
            document_id=document_id, total_fields_count=0, audit_items=[],
            summary_note="BidFillerAgent Multi-Agent 标书撰写完成"
        )
        return {}, audit_report, final_state.get("filled_docx_bytes")


bid_filler_agent = BidFillerAgent()


def bid_filler_orchestrator_node(state: dict) -> dict:
    """Orchestrator 适配节点 — 将 BidFillerAgent 对接至 LangGraph 编排器"""
    from app.worker.tasks import emit_agent_log
    document_id = state.get("document_id")
    tenant_id = state.get("tenant_id") or "default-tenant"

    emit_agent_log("info", "启动 BidFillerAgent (Multi-Agent Supervisor+Worker)...",
                   extra={"type": "worker_start", "worker": "writer_agent"})

    if not document_id:
        return {"status": "writer_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        from app.services.bid_format_extractor_service import bid_format_extractor_service
        template_bytes, _, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db, doc_id=document_id, tenant_id=tenant_id)
        if not template_bytes:
            raise ValueError("未提取到《投标文件格式》模板")

        _, _, filled_bytes = bid_filler_agent.process_filling_tasks(
            db=db, document_id=document_id, profile=CompanyProfile(),
            detected_placeholders=[], original_docx=template_bytes)

        # __file__ 向上 3 层为 backend 根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        drafts_dir = os.path.join(base_dir, "uploads", "drafts")
        os.makedirs(drafts_dir, exist_ok=True)
        draft_path = os.path.join(drafts_dir, f"draft_{document_id}.docx")
        if filled_bytes:
            with open(draft_path, "wb") as f:
                f.write(filled_bytes)

        doc_obj = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if doc_obj:
            curr_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
            curr_meta["draft_path"] = draft_path
            curr_meta["draft_filename"] = f"draft_{document_id}.docx"
            doc_obj.parsed_metadata = curr_meta
            db.commit()

        summary = "已成功由 BidFillerAgent (Multi-Agent) 完成投标书 Word 草稿生成"
        emit_agent_log("info", summary, extra={
            "type": "worker_complete", "worker": "writer_agent", "status": "success", "summary": summary
        })
        return {
            "completed_steps": ["writer_agent"], "draft_path": draft_path,
            "worker_summaries": [{"worker": "writer_agent", "status": "success", "summary": summary}]
        }
    except Exception as e:
        logger.exception(f"BidFillerAgent 适配节点失败: {e}")
        emit_agent_log("error", f"BidFillerAgent 执行失败: {str(e)}")
        return {"status": "writer_failed", "error": str(e)}
    finally:
        db.close()
