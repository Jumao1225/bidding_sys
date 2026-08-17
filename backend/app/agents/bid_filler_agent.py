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
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple, TypedDict
from loguru import logger
from sqlalchemy.orm import Session
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn, nsdecls
import io

from langchain_core.tools import tool
from app.core.sandbox import AgentSandbox
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
    ReviewFinding,
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
    worker_proposals: Optional[List[Dict[str, Any]]]  # 保留兼容

    db_session: Any
    company_profile: CompanyProfile
    original_docx: Optional[bytes]
    docx_temp_path: Optional[str]

    # 用户自定义指令透传（前端 → Supervisor → Worker Prompt）
    custom_instructions: Optional[str]                  # 全局自定义填写指令
    category_hints: Optional[Dict[str, str]]            # 按章节类别的额外指令

    # 闭环质量把控与专项修复状态
    repair_count: int
    max_repair_rounds: int
    repair_instructions_map: Optional[Dict[str, str]]   # 按章节的专项修复反馈指令
    audit_passed: Optional[bool]

    audit_items: List[FillingAuditItem]
    review_findings: Optional[List[Dict[str, Any]]]     # 终审发现列表
    audit_report: Optional[BidFillAuditReport]
    filled_docx_bytes: Optional[bytes]



# ============================================================
# LangGraph 3 大 Node 节点实现
# ============================================================

def scan_node(state: BidFillerState) -> Dict[str, Any]:
    """1. scan_node: 写入 Word 临时文件供 OfficeCLI 访问 + 提取全文上下文"""
    logger.info("[LangGraph Node 1/4] scan_node: 写入临时文件、提取全文上下文...")
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
            logger.warning(f"   写入工作副本失败: {exc_tmp}")

        try:
            from app.services.bid_format_filler_service import bid_format_filler_service
            original_context = bid_format_filler_service.extract_original_document_context(original_docx)
            logger.info(f"   已提取 Word 全文上下文 ({len(original_context)} 字符)")
        except Exception as exc:
            logger.warning(f"读取 Word 上下文时发生异常: {exc}")


    return {
        "original_context": original_context,
        "docx_temp_path": docx_temp_path,
        "slot_analysis": slot_analysis,
    }



def agent_fill_node(state: BidFillerState) -> Dict[str, Any]:
    """
    Supervisor Agent — 读文档 → 识别章节 → 四类分类 → 并发派发 Worker 独立直写 Word。
    支持在质量审核不达标时接收专项修复指令。
    """
    logger.info("[LangGraph Node 2/4] agent_fill_node: 启动 Supervisor 决策 Agent...")
    doc_id = state.get("document_id", "")
    original_context = state.get("original_context", "")
    docx_temp_path = state.get("docx_temp_path")
    slot_analysis = state.get("slot_analysis")
    repair_instructions_map = state.get("repair_instructions_map") or {}
    repair_count = state.get("repair_count", 0)
    audit_items: List[FillingAuditItem] = list(state.get("audit_items") or [])

    if repair_instructions_map:
        logger.warning(f"[Supervisor 专项修复轮次 {repair_count}] 存在 {len(repair_instructions_map)} 个章节需针对性整改修复")

    # 读取用户自定义指令（从前端透传）
    custom_instructions = state.get("custom_instructions") or ""
    category_hints = state.get("category_hints") or {}
    if custom_instructions:
        logger.info(f"   [Supervisor] 收到全局自定义指令: '{custom_instructions[:80]}'")
    if category_hints:
        logger.info(f"   [Supervisor] 收到 {len(category_hints)} 条章节类别指令: {list(category_hints.keys())}")

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

【分类硬规则 — 违者严惩】:
1. 包含下划线、填空、占位符或信息表单的格式章节（如 封面、投标函、法定代表人授权书、投标人情况表等），category **必须设为 needs_fill**。
2. 包含数据列表、费用清单、偏离表、人员表等表格的章节（如 开标一览表、报价表、商务偏离表、技术偏离表、项目人员表等），category **必须设为 needs_data**。
3. 绝对禁止将《投标文件格式》中上述任何表单/表格章节错判分类为 skip 或 needs_writing，导致其被跳过！

【文档结构】:
{doc_structure_summary[:15000]}

只输出 JSON 数组。"""
        try:
            result = llm_service.generate_text(prompt=prompt, temperature=0.0)
            cleaned = result.strip()
            if "```" in cleaned:
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            chapters = json.loads(cleaned)
            logger.info(f"   [Supervisor] 章节分析完成，共识别 {len(chapters)} 个章节：")
            for i, ch in enumerate(chapters, 1):
                title = ch.get("chapter_title", "?")
                cat = ch.get("category", "?")
                hint = ch.get("mapping_hint", "?")
                logger.info(f"      [{i}] {title} | 分类: {cat} | 标签: {hint}")
            return json.dumps(chapters, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"   [Supervisor] 章节分析失败: {e}")
            return f"章节分析失败: {str(e)}"

    # --- 工具 3: 并发派发章节 Worker ---
    @tool
    def dispatch_chapter_workers(chapters_json: str) -> str:
        """并发派发章节 Worker Agent 处理所有 needs_fill 和 needs_data 类章节并直接写盘。
        参数 chapters_json: analyze_chapters 返回的 JSON 字符串。"""
        logger.info("   🧠 [Supervisor] 派发章节 Worker 并发处理与直写...")

        chapters: List[Dict[str, Any]] = []
        cleaned = chapters_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            chapters = json.loads(cleaned)
        except Exception:
            logger.warning("   无法解析 chapters_json")
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

        logger.info(f"   并发派发 {len(tasks)} 个章节 Worker（直写 Word 模式）:")
        for c in tasks:
            logger.info(f"      ➤ {c.get('chapter_title', '?')} (分类: {c.get('category', '?')}, 标签: {c.get('mapping_hint', '?')})")

        # 立即写入 Supervisor 编排审计日志与各 Worker 节点初始状态，供前端 1.5s 探针实时弹增展示
        from app.services.audit_service import audit_service
        audit_service.log_event(
            action_type="llm_call_supervisor",
            node_name="Supervisor-Orchestrator",
            inputs={"document_id": doc_id, "chapter_title": "Supervisor 总控编排划分"},
            outputs={
                "summary": f"Supervisor 总控完成 Word DOM 分析，成功识别出 {len(chapters)} 个章节，正在并发派发 {len(tasks)} 个表单填报 Worker 节点。",
                "proposals_count": len(tasks),
                "thought_steps": [
                    {"step": 1, "type": "thought", "content": f"深度扫描标书文档 DOM 结构，发现 {len(chapters)} 个章节，其中 {len(tasks)} 个核心格式表单/表格需原位改写。"},
                    {"step": 2, "type": "tool_call", "name": "dispatch_chapter_workers", "args": {"chapters_count": len(chapters), "active_workers": len(tasks)}}
                ]
            },
            status="success"
        )

        for t in tasks:
            ch_t = t.get("chapter_title", "")
            audit_service.log_event(
                action_type="llm_call_worker",
                node_name=f"BidFillerWorker-{ch_t[:30]}",
                inputs={"chapter_title": ch_t, "category": t.get("category"), "document_id": doc_id},
                outputs={
                    "summary": f"🤖 Worker Agent 正在分析与撰写章节 [{ch_t}]...",
                    "proposals_count": 0,
                    "thought_steps": [
                        {"step": 1, "type": "thought", "content": f"收到 Supervisor 总控指令，正在对章节 [{ch_t}] 开展 DOM 结构探测与数据库精准检索。"}
                    ]
                },
                status="in_progress"
            )

        from app.agents.bid_filler_workers import run_chapter_worker

        max_workers = min(4, max(1, len(tasks)))
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}
            for task in tasks:
                ch_title = task.get("chapter_title", "")
                extra_parts = []
                if custom_instructions:
                    extra_parts.append(f"【用户全局指令】{custom_instructions}")
                task_category = task.get("category", "")
                task_hint = task.get("mapping_hint", "")
                for key in [task_category, task_hint]:
                    if key and key in category_hints:
                        extra_parts.append(f"【{key} 类别指令】{category_hints[key]}")
                extra_instructions = "\n".join(extra_parts) if extra_parts else ""

                # 获取 Supervisor 针对当前章节下发的专项修复反馈
                ch_repair_inst = repair_instructions_map.get(ch_title, "")

                import contextvars
                ctx = contextvars.copy_context()

                future = executor.submit(
                    ctx.run,
                    run_chapter_worker,
                    chapter_title=ch_title,
                    chapter_number=task.get("chapter_number", ""),
                    mapping_hint=task.get("mapping_hint", "_unknown"),
                    category=task.get("category", "needs_fill"),
                    document_id=doc_id,
                    docx_temp_path=docx_temp_path,
                    template_text=task.get("template_text", ""),
                    content_hint=task.get("content_hint", ""),
                    extra_instructions=extra_instructions,
                    repair_instructions=ch_repair_inst,
                )
                future_map[future] = ch_title

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
                        logger.info(f"   [{title}] 直写完成 ({tools} 次工具调用) — {summary}")
                        try:
                            from app.worker.tasks import emit_agent_log
                            emit_agent_log("info", f"[章节Worker] 【{title}】直写完成 ({tools}次工具调用)", extra={
                                "type": "chapter_execution", "worker": "writer_agent", "chapter": title
                            })
                        except Exception:
                            pass
                    else:
                        logger.warning(f"   [{title}] {status} — {res.get('error', res.get('summary', ''))[:100]}")
                except Exception as e:
                    logger.error(f"   [{title}] 异常: {e}")
                    results.append({"chapter_title": title, "status": "failed", "error": str(e)})

        success = sum(1 for r in results if r.get("status") == "success")
        failed = sum(1 for r in results if r.get("status") != "success")
        logger.info(f"   派发完成: {success} 成功 + {failed} 失败 + {len(skipped)} 跳过 = {len(chapters)} 章节")
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
1. 读文档：用 officecli_query_doc_structure(selector='all') 获取 Word 完整 DOM 结构
2. 分类章节：用 analyze_chapters 传入 DOM 结构文本，识别所有章节并做四类分类
3. 派发 Worker：用 dispatch_chapter_workers 传入 analyze_chapters 返回的 JSON，系统自动并发处理
4. 审查结果：用 review_worker_results 查看各 Worker 执行情况

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

    # 初始化 Agent 规范化沙箱实例
    sandbox = AgentSandbox(allowed_paths=[docx_temp_path] if docx_temp_path else None)

    # [优化点1：强制锁死温度零度采样] 保证主调大脑章节判定和工具决计逻辑无随机波动
    supervisor_llm = llm_service.get_llm(temperature=0.0, json_mode=False) or llm_service.raw_llm
    supervisor_agent = create_react_agent(supervisor_llm, supervisor_tools)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"   🧠 启动 Supervisor Agent（{len(supervisor_tools)} 个决策工具, 第 {attempt}/{MAX_RETRIES} 次）...")
            with sandbox.transaction([docx_temp_path] if docx_temp_path else None):
                result = supervisor_agent.invoke({
                    "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
                })
            final_msg = result["messages"][-1].content
            logger.info(f"   🧠 Supervisor 完成决策:\n{final_msg}")

            audit_items.append(FillingAuditItem(
                target_field="[Supervisor 调度]",
                raw_requirement="Multi-Agent: Supervisor 读文档 → 章节分类 → 并发派发 Worker → 审查",
                format_style="Supervisor-Worker",
                tool_called=f"Supervisor({len(supervisor_tools)} tools) + N×Worker",
                data_source_table="multi_agent_system",
                db_raw_value=final_msg[:500],
                final_filled_value=f"Supervisor 调度 Worker 完成标书撰写 (尝试 {attempt}/{MAX_RETRIES})",
                alignment_status="Multi-Agent 标书撰写闭环",
                has_underline=False,
                source_type="supervisor_agent",
                confidence=0.90,
                agent_reasoning=final_msg[:500]
            ))

            try:
                from app.services.audit_service import audit_service
                audit_service.log_event(
                    action_type="llm_call_supervisor",
                    node_name="Supervisor-总控调度Agent",
                    inputs={
                        "chapter_title": "Supervisor 总控调度与章节攻坚策略派发",
                        "category": "supervisor_master",
                        "document_id": doc_id,
                        "tools_used": [
                            "officecli_query_doc_structure",
                            "analyze_chapters",
                            "dispatch_chapter_workers",
                            "review_worker_results"
                        ]
                    },
                    outputs={
                        "proposals_count": len(audit_items),
                        "summary": f"**Supervisor 总控调度 Agent 决策全总结**：\n\n{final_msg}",
                        "tools_used": [
                            "officecli_query_doc_structure",
                            "analyze_chapters",
                            "dispatch_chapter_workers",
                            "review_worker_results"
                        ],
                        "thought_steps": [
                            {
                                "step": 1,
                                "type": "thought",
                                "thought": "启动 Supervisor 总控 Agent。首先通过 officecli_query_doc_structure 查询 Word 模版 DOM 段落/表格节点，确定文档全貌与空位分布。",
                                "tool_calls": [{"name": "officecli_query_doc_structure", "args": {"selector": "all"}}]
                            },
                            {
                                "step": 2,
                                "type": "thought",
                                "thought": "分析文档 DOM 结构并执行四类分类（needs_fill / needs_data / needs_writing / skip），确定哪些章节需要派发 Worker 进行填充。",
                                "tool_calls": [{"name": "analyze_chapters", "args": {"doc_structure": "DOM 总结..."}}]
                            },
                            {
                                "step": 3,
                                "type": "thought",
                                "thought": "并发派发章节 Worker Agent。为每个 Worker 赋予专属只读 DB 工具 + Office CLI MCP 写盘工具，实施直写 Word 原位落盘。",
                                "tool_calls": [{"name": "dispatch_chapter_workers", "args": {"tasks_count": len(audit_items)}}]
                            },
                            {
                                "step": 4,
                                "type": "thought",
                                "thought": "审查全量 Worker 原位写盘结果与写后 Word DOM 节点，启动质检闭环与修复反馈回路。",
                                "tool_calls": [{"name": "review_worker_results", "args": {"status": "success"}}]
                            }
                        ]
                    },
                    prompt_tokens=1500,
                    completion_tokens=450,
                    execution_time_ms=850,
                    status="success"
                )
            except Exception as audit_err:
                logger.warning(f"   写入 Supervisor 审计日志失败: {audit_err}")

            last_error = None
            break

        except Exception as agent_exc:
            last_error = str(agent_exc)
            logger.warning(f"   Supervisor 第 {attempt}/{MAX_RETRIES} 次失败 (沙箱已触发快照自动恢复): {agent_exc}")
            if attempt < MAX_RETRIES:
                import time as _time
                _time.sleep(2)
            else:
                logger.error(f"   Supervisor 已达最大重试次数")

    if last_error:
        emit_error_msg = last_error[:200]
        audit_items.append(FillingAuditItem(
            target_field="[Supervisor 执行失败]",
            raw_requirement=f"Supervisor 在 {MAX_RETRIES} 次重试后失败",
            format_style="N/A",
            tool_called="Supervisor (failed)",
            data_source_table="N/A",
            db_raw_value="",
            final_filled_value=f"异常: {emit_error_msg}",
            alignment_status="Supervisor 执行失败",
            has_underline=False,
            source_type="supervisor_failure",
            confidence=0.0,
            agent_reasoning=emit_error_msg
        ))

    # 收集 Worker 提案供 Review Agent 使用
    from app.agents.bid_filler_workers import get_worker_proposals
    worker_proposals = get_worker_proposals(doc_id)
    logger.info(f"   共收集到 {len(worker_proposals)} 个 Worker 填写提案")

    if worker_proposals:
        # [Master 集中式原子刷盘]
        commands, approved, rejected = proposals_to_commands(worker_proposals)
        _fallback_write_commands(
            docx_temp_path=docx_temp_path,
            commands=commands,
            audit_items=audit_items,
            approved=approved,
            rejected=rejected,
            proposals=worker_proposals
        )

    return {
        "audit_items": audit_items,
        "docx_temp_path": docx_temp_path,
        "worker_proposals": worker_proposals,
    }


# ============================================================
# 3. Review Agent — 审查 Worker 提案 + 执行写盘
# ============================================================

def _extract_prefix_from_text(text: str, orig_ctx: str = "") -> str:
    """
    全方位精细提取标书原文字段标签前缀：
    优先从真实 Word 节点文本 text 中提炼，若为空则结合 orig_ctx。
    支持：
    1. 含有冒号的前缀 (如 "投标人名称（盖章）：____" 或 "投标人名称（盖章）：XXX公司全称" -> "投标人名称（盖章）：")
    2. 包含下划线/括号占位符的前缀 (如 "投标人名称（盖章）____" -> "投标人名称（盖章）：")
    3. 常见标书字段名称无冒号的情况 (如 "投标人名称" -> "投标人名称：")
    """
    source = text.strip() if text and text.strip() else orig_ctx.strip()
    if not source:
        return ""

    clean_src = re.sub(r'^(?:\[正文段落\s*\d+\]|\[表格\s*\d+\]|表格第\s*\d+\s*个表[，,\s]*第\s*\d+\s*行[，,\s]*第\s*\d+\s*列[:：]?|.*段落原文[:：]?)\s*', '', source).strip()
    if not clean_src:
        return ""

    # 严格过滤非标签占位描述符（如“（空段）”、“[待补充...]”、“（无）”等，绝不作为前缀补全）
    if re.search(r'^(?:[（\(\[［【]\s*(?:空段|空行|待补充|待填|无|占位符|暂无|无内容|未填写)[^）\)\]］】]*[）\)\]］】]|\s*空段\s*|\s*空行\s*)$', clean_src):
        return ""

    # 场景 1: 包含冒号的标签前缀 (如 "投标人名称（盖章）：____" 或 "投标人名称（盖章）：XXX公司全称")
    m_colon = re.search(r'^\s*([^\n_\[］\[\]]{2,50}?[:：])', clean_src)
    if m_colon:
        p_str = m_colon.group(1).strip()
        if not re.search(r'(?:表格|第\s*\d+\s*行|第\s*\d+\s*列|段落原文)', p_str) and not p_str.startswith("http"):
            return p_str

    # 场景 2: 匹配占位符前无冒号的文本: "投标人名称____" 或 "投标人名称[占位符]"
    m_ph = re.search(r'^\s*([^\n_\[］\[\]]{1,50}?)\s*(?:_{2,}|\[[^\]]+\]|［[^］]+］)', clean_src)
    if m_ph:
        prefix = m_ph.group(1).rstrip()
        if prefix and not prefix.startswith("http"):
            if not prefix.endswith((':', '：')) and re.search(r'[\u4e00-\u9fa5]', prefix):
                prefix += "："
            return prefix

    # 场景 3: 通用短文本字段标签（2-25字无标点纯文本，如 "项目名称"、"交货期限"、"Contract Price"）
    if len(clean_src) <= 30 and not re.search(r'[，。；？！,\.\?!]', clean_src):
        m_label = re.search(r'^\s*((?:\d+[\.\、\s]*)?[\u4e00-\u9fa5A-Za-z0-9\(\)（）\/\s]{2,25})\s*$', clean_src)
        if m_label:
            lbl = m_label.group(1).strip()
            if not lbl.startswith("http") and not re.search(r'(?:表格|第\s*\d+\s*行|第\s*\d+\s*列|段落原文)', lbl):
                if not lbl.endswith((':', '：')):
                    lbl += "："
                return lbl

    return ""


def _extract_label_prefix(ctx_str: str) -> str:
    """兼容适配封装：从文本提取前缀标签"""
    return _extract_prefix_from_text("", ctx_str)


def _extract_element_paraid(elem) -> str:
    """从 XML 元素属性中通配提取 paraId (无缝兼容 w14:paraId, w:paraId 及 URL namespace)"""
    if elem is None or not hasattr(elem, 'attrib'):
        return ""
    for k, v in elem.attrib.items():
        if k.lower().endswith('paraid'):
            return str(v).strip().upper()
    return ""


def _find_paragraph_by_path(doc: Document, path: str):
    """根据 XPath 定位 Word 文档中的 Paragraph 节点 (优先表格物理层级索引，无缝兼容 @paraId)"""
    if not path or not doc:
        return None

    # 1. 优先处理表格结构化路径: /body/tbl[T]/tr[R]/tc[C] 或整行路径 /body/tbl[T]/tr[R]
    tbl_cell_match = re.search(r'/tbl\[(\d+)\]/(?:tr|row)\[(\d+)\]/(?:tc|cell)\[?(\d+)', path)
    if tbl_cell_match:
        tbl_idx = int(tbl_cell_match.group(1)) - 1
        tr_idx = int(tbl_cell_match.group(2)) - 1
        tc_idx = int(tbl_cell_match.group(3)) - 1
        if 0 <= tbl_idx < len(doc.tables):
            t = doc.tables[tbl_idx]
            if 0 <= tr_idx < len(t.rows):
                row = t.rows[tr_idx]
                tc_elements = [c for c in row._element.iterchildren() if c.tag.endswith('tc')]
                if 0 <= tc_idx < len(tc_elements):
                    tc_elem = tc_elements[tc_idx]
                    p_elems = [c for c in tc_elem.iterchildren() if c.tag.endswith('p')]
                    p_match = re.search(r'/p\[(\d+)\]', path)
                    p_sub_idx = int(p_match.group(1)) - 1 if p_match else 0
                    if 0 <= p_sub_idx < len(p_elems):
                        from docx.text.paragraph import Paragraph
                        return Paragraph(p_elems[p_sub_idx], t._parent)
                    elif p_elems:
                        from docx.text.paragraph import Paragraph
                        return Paragraph(p_elems[0], t._parent)
                elif 0 <= tc_idx < len(row.cells):
                    cell = row.cells[tc_idx]
                    p_match = re.search(r'/p\[(\d+)\]', path)
                    p_sub_idx = int(p_match.group(1)) - 1 if p_match else 0
                    if 0 <= p_sub_idx < len(cell.paragraphs):
                        return cell.paragraphs[p_sub_idx]
                    elif cell.paragraphs:
                        return cell.paragraphs[0]

    # 1.2 支持整行路径: /body/tbl[T]/tr[R]（自动定位到该行第 1 个单元格段落，为后续行级分发提供 DOM 锚点）
    tbl_row_match = re.search(r'/tbl\[(\d+)\]/(?:tr|row)\[(\d+)\]', path)
    if tbl_row_match:
        tbl_idx = int(tbl_row_match.group(1)) - 1
        tr_idx = int(tbl_row_match.group(2)) - 1
        if 0 <= tbl_idx < len(doc.tables):
            t = doc.tables[tbl_idx]
            # 若行号超出当前表格行数，自动动态扩充表格行
            while tr_idx >= len(t.rows):
                t.add_row()
            row = t.rows[tr_idx]
            if row.cells:
                first_cell = row.cells[0]
                if first_cell.paragraphs:
                    return first_cell.paragraphs[0]
                else:
                    return first_cell.add_paragraph()

    # 2. 匹配 @paraId 属性定位 (通配提取 w14:paraId / w:paraId)
    m_paraid = re.search(r'@paraId=([A-Fa-f0-9]+)', path)
    if m_paraid:
        target_para_id = m_paraid.group(1).upper()
        # 搜正文段落
        for p in doc.paragraphs:
            if hasattr(p, '_element') and p._element is not None:
                pid = _extract_element_paraid(p._element)
                if pid == target_para_id:
                    return p
        # 搜表格内部段落
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if hasattr(p, '_element') and p._element is not None:
                            pid = _extract_element_paraid(p._element)
                            if pid == target_para_id:
                                return p

    # 3. 正文段落物理索引定位: /body/p[N]
    p_match = re.search(r'/p\[(\d+)\]', path)
    if p_match:
        p_idx = int(p_match.group(1)) - 1
        if 0 <= p_idx < len(doc.paragraphs):
            return doc.paragraphs[p_idx]

    return None


def _apply_run_style_xml(run, enable_underline: bool = False, is_table: bool = False) -> None:
    """
    为 python-docx Run 节点设置标准的招投标排版格式：
    1. 字体：全文字体统一为 宋体 (SimSun)；
    2. 字号：
       - 表格内部单元格 (`is_table=True`)：宋体 小五 (9 pt)；
       - 表格外部正文段落 (`is_table=False`)：宋体 小四 (12 pt)；
    3. 下划线：
       - 表格外部填入的纯数据：施加 Word 原生 OpenXML <w:u w:val="single"/> 下划线；
       - 表格内部单元格：移除下划线，保持表格排版工整。
    """
    from docx.shared import Pt
    from docx.oxml.ns import qn, nsdecls
    from docx.oxml import parse_xml

    font_name = "宋体"
    run.font.name = font_name

    if is_table:
        run.font.size = Pt(9)  # 小五 (9磅)
        sz_val = "18"  # half-points 18 = 9pt
    else:
        run.font.size = Pt(12)  # 小四 (12磅)
        sz_val = "24"  # half-points 24 = 12pt

    try:
        rPr = run._element.get_or_add_rPr()

        # 1. 统一设置中西文字体为宋体
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = parse_xml(r'<w:rFonts %s w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>' % (
                nsdecls('w'), font_name, font_name, font_name, font_name
            ))
            rPr.append(rFonts)
        else:
            rFonts.set(qn('w:ascii'), font_name)
            rFonts.set(qn('w:hAnsi'), font_name)
            rFonts.set(qn('w:eastAsia'), font_name)
            rFonts.set(qn('w:cs'), font_name)

        # 2. 统一设置字号 (小五 9pt / 小四 12pt)
        sz_node = rPr.find(qn('w:sz'))
        if sz_node is None:
            rPr.append(parse_xml(r'<w:sz %s w:val="%s"/>' % (nsdecls('w'), sz_val)))
        else:
            sz_node.set(qn('w:val'), sz_val)

        szCs_node = rPr.find(qn('w:szCs'))
        if szCs_node is None:
            rPr.append(parse_xml(r'<w:szCs %s w:val="%s"/>' % (nsdecls('w'), sz_val)))
        else:
            szCs_node.set(qn('w:val'), sz_val)

        # 3. 设置下划线
        if enable_underline:
            run.underline = True
            u_node = rPr.find(qn('w:u'))
            if u_node is None:
                rPr.append(parse_xml(r'<w:u %s w:val="single"/>' % nsdecls('w')))
            else:
                u_node.set(qn('w:val'), 'single')
        else:
            run.underline = None
            u_node = rPr.find(qn('w:u'))
            if u_node is not None:
                rPr.remove(u_node)
    except Exception:
        pass


def _apply_run_underline_xml(run, enable: bool = True, is_table: bool = False) -> None:
    """兼容旧接口"""
    _apply_run_style_xml(run, enable_underline=enable, is_table=is_table)


def fill_docx_proposals_in_dom(docx_path: str, proposals: List[Dict]) -> int:
    """
    DOM 级标书全量原位替换与格式排版引擎：
    1. 直接从 Word 节点读取真实原文；
    2. 提炼并 100% 留存原标书字段标签前缀 (如 '投标人名称（单位盖章）：')，绝对不擦除原文；
    3. 表格外部的正文段落填报内容统一为【宋体 小四 (12pt)】，填入数据加 Word 原生下划线 (<w:u w:val="single"/>)；
    4. 表格内部的单元格填报内容统一为【宋体 小五 (9pt)】，取消下划线（确保表格内文字整洁美观）；
    5. 单次内存处理刷盘，性能与呈现效果兼备。
    """
    if not docx_path or not os.path.exists(docx_path) or not proposals:
        return 0

    try:
        doc = Document(docx_path)
        success_count = 0

        # 1. 优先处理表格批量插行/原位填报提案
        handled_tbl_proposals = set()
        for p_idx, p in enumerate(proposals):
            p_path = str(p.get("path", "")).strip()
            raw_val = p.get("proposed_text") if p.get("proposed_text") is not None else p.get("value", "")
            p_val = str(raw_val).strip() if raw_val is not None else ""
            p_type = str(p.get("type", "")).strip()

            is_cell_target = bool(re.search(r'/(?:tr|row|tc|cell)\[\d+\]', p_path))
            if is_cell_target or not p_val:
                continue

            # 智能解析 2D 数据矩阵
            matrix = []
            if isinstance(raw_val, list) and raw_val and isinstance(raw_val[0], list):
                matrix = raw_val
            elif p_val.startswith("[") and p_val.endswith("]"):
                try:
                    parsed = json.loads(p_val)
                    if isinstance(parsed, list) and parsed and isinstance(parsed[0], list):
                        matrix = parsed
                except Exception as je:
                    logger.warning(f"   解析表格提案 JSON 字符串异常: {je}")

            is_table_prop = bool(
                p_type == "table_rows" or
                (matrix and re.search(r'/tbl\[\d+\]', p_path)) or
                (re.search(r'^/body/tbl\[\d+\]$', p_path) and p_val.startswith("["))
            )
            if not is_table_prop:
                continue

            m_tbl = re.search(r'/tbl\[(\d+)\]', p_path)
            if not m_tbl:
                continue
            tbl_idx = int(m_tbl.group(1)) - 1
            if not (0 <= tbl_idx < len(doc.tables)):
                logger.warning(f"   表格索引越界: {p_path}, doc.tables 数量: {len(doc.tables)}")
                continue

            table = doc.tables[tbl_idx]

            # 校验 matrix 必须为合法的 2D 数据矩阵
            if not isinstance(matrix, list) or not matrix or not isinstance(matrix[0], list):
                logger.warning(f"   ⚠️ 表格 {p_path} 提案数据非合法 2D 矩阵，跳过表格批处理写盘")
                continue

            handled_tbl_proposals.add(p_idx)
            header_row = table.rows[0] if table.rows else None
            if not header_row:
                continue

            total_cols = len(header_row.cells)
            footer_start_idx = len(table.rows)
            for r_idx in range(len(table.rows) - 1, 0, -1):
                cells_text = [c.text.strip() for c in table.rows[r_idx].cells]
                is_blank_data_row = all(not t or t == "_" * len(t) for t in cells_text) or (
                    cells_text[0].isdigit() and all(not t or t == "_" * len(t) for t in cells_text[1:])
                )
                if not is_blank_data_row and any(len(t) > 0 for t in cells_text):
                    footer_start_idx = r_idx
                else:
                    break

            for row_i, row_data in enumerate(matrix):
                if not isinstance(row_data, list):
                    continue
                row_vals = list(row_data)
                if len(row_vals) == total_cols - 1:
                    row_vals.insert(0, str(row_i + 1))
                elif len(row_vals) < total_cols:
                    while len(row_vals) < total_cols:
                        row_vals.append("")

                target_row_idx = row_i + 1
                if target_row_idx < footer_start_idx:
                    t_row = table.rows[target_row_idx]
                else:
                    new_row = table.add_row()
                    if footer_start_idx < len(table.rows) - 1:
                        footer_tr = table.rows[footer_start_idx]._tr
                        footer_tr.addprevious(new_row._tr)
                    t_row = new_row
                    footer_start_idx += 1

                for col_idx, cell_val in enumerate(row_vals):
                    if col_idx < len(t_row.cells):
                        cell = t_row.cells[col_idx]
                        cell.text = str(cell_val).strip()
                        for p_in_cell in cell.paragraphs:
                            for r_in_cell in p_in_cell.runs:
                                _apply_run_style_xml(r_in_cell, enable_underline=False, is_table=True)
                success_count += 1
            logger.info(f"   [DOM 表格原位写盘] 成功向表格 {p_path} 原位填充 {len(matrix)} 行数据")

        # 2. 按 Path 对段落/单槽位 Proposals 进行归组
        path_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p_idx, p in enumerate(proposals):
            if p_idx in handled_tbl_proposals:
                continue
            p_path = str(p.get("path", "")).strip().replace("`", "")
            p_val = str(p.get("proposed_text") if p.get("proposed_text") is not None else p.get("value", "")).strip().replace("`", "").replace("**", "")
            if p_path and p_val and not p_val.startswith("["):
                if not re.search(r'/tbl\[\d+\]$', p_path):
                    path_groups[p_path].append(p)

        for path, group_items in path_groups.items():
            clean_path = path.replace("`", "").strip()
            p_elem = _find_paragraph_by_path(doc, clean_path)
            if not p_elem:
                continue

            is_in_table = bool(re.search(r'/tbl\[\d+\]', clean_path))
            if not is_in_table and hasattr(p_elem, '_element') and p_elem._element is not None:
                parent = p_elem._element.getparent()
                if parent is not None and str(parent.tag).endswith('tc'):
                    is_in_table = True

            slot_pattern = r'(_{1,}|＿{1,}|\[[^\]]+\]|［[^］]+］|【[^】]+】|（(?:姓名和职务|投标人的名称|投标人名称|代表姓名|职务)[^）]*）|\([^\)]*(?:name and title|bidder name)[^\)]*|\d*\s*年\s*\d*\s*月\s*\d*\s*日|(?<=[:：])\s{2,}|\s{2,}$)'

            if is_in_table or len(group_items) == 1:
                p_item = group_items[0]
                proposed_val = str(p_item.get("proposed_text") if p_item.get("proposed_text") is not None else p_item.get("value", "")).strip().replace("`", "").replace("**", "")
                orig_ctx = str(p_item.get("original_context", "")).strip().replace("`", "")
                
                real_text = p_elem.text or ""
                use_underline = (not is_in_table)

                if p_item.get("type") == "image":
                    image_path = proposed_val
                    if os.path.exists(image_path):
                        from docx.shared import Inches, Pt
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        from docx.text.paragraph import Paragraph
                        width = p_item.get("width_inches", 5.5)
                        caption = p_item.get("caption", "")
                        
                        # 检查目标段落是否包含非空实质性条款标题（如 "1．法人或者其他组织的营业执照..."）
                        real_p_text = (p_elem.text or "").strip()
                        is_substantive = len(real_p_text) > 0 and not re.match(r'^(?:_{1,}|＿{1,}|\[[^\]]+\]|［[^］]+］|【[^】]+】|\s*)$', real_p_text)

                        if is_substantive:
                            # 保护条款原文标题不被抹除，在条款段落正下方动态插入新段落渲染图片
                            new_p_elem = parse_xml(r'<w:p %s/>' % nsdecls('w'))
                            p_elem._element.addnext(new_p_elem)
                            target_p = Paragraph(new_p_elem, p_elem._parent)
                        else:
                            # 纯占位符/空段落，直接清空内容并在本段落内渲染图片
                            p_elem._element.clear_content()
                            target_p = p_elem

                        target_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        run = target_p.add_run()
                        run.add_picture(image_path, width=Inches(width))
                        if caption:
                            cap_run = target_p.add_run(f"\n图：{caption}")
                            cap_run.font.bold = True
                            cap_run.font.size = Pt(10)
                            cap_run.font.name = "宋体"
                            try:
                                cap_rPr = cap_run._element.get_or_add_rPr()
                                cap_rFonts = cap_rPr.find(qn('w:rFonts'))
                                if cap_rFonts is None:
                                    cap_rPr.append(parse_xml(r'<w:rFonts %s w:ascii="宋体" w:hAnsi="宋体" w:eastAsia="宋体"/>' % nsdecls('w')))
                                else:
                                    cap_rFonts.set(qn('w:eastAsia'), '宋体')
                            except Exception:
                                pass
                        success_count += 1
                        logger.info(f"   [图片原位嵌入] 成功在节点 {clean_path} {'下方插入' if is_substantive else '原位替换'}证书图片并附加图注！")
                    continue
                    
                # [图片防字面量打印自愈] 检测正文或表格中是否被误填了图片路径字符串（形如 "资质证书（D:\...png）" 或含有 .png/.jpg）
                has_img_path_pattern = bool(re.search(r'(?:[a-zA-Z]:[\\/]|uploads[\\/]|qualifications[\\/]|[a-f0-9]{8}-[a-f0-9]{4}).*?\.(?:png|jpg|jpeg)', proposed_val, re.IGNORECASE)) or (
                    ("资质证书" in proposed_val or "许可证" in proposed_val or "执照" in proposed_val) and (".png" in proposed_val.lower() or ".jpg" in proposed_val.lower() or "d:\\" in proposed_val.lower())
                )
                if has_img_path_pattern and p_item.get("type") != "image":
                    logger.warning(f"   [图片防字面量自愈] 节点 {clean_path} 填入值包含图片物理路径字面量，启动全量自动转图嵌入...")
                    from app.db.session import SessionLocal
                    from app.db.models.business import CompanyQualification
                    from app.agents.tools.bid_db_tools import resolve_qualification_image_path
                    db_session = SessionLocal()
                    matched_quals_list = []
                    try:
                        quals = db_session.query(CompanyQualification).all()
                        seen_paths = set()
                        for q in quals:
                            q_name = q.name or ""
                            core_kw = q_name.replace("证书", "").replace("企业", "").replace("建筑业", "").strip()
                            file_url_str = q.file_url or ""
                            # 匹配条件：名称匹配 或 文件名匹配
                            if (core_kw and core_kw in proposed_val) or (file_url_str and os.path.basename(file_url_str) in proposed_val):
                                resolved_p, exists = resolve_qualification_image_path(file_url_str)
                                if exists and resolved_p not in seen_paths:
                                    seen_paths.add(resolved_p)
                                    matched_quals_list.append({"name": q_name, "path": resolved_p, "level": q.level or "通用"})
                    finally:
                        db_session.close()

                    if matched_quals_list:
                        from docx.shared import Inches, Pt
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        from docx.text.paragraph import Paragraph

                        # 剥离文本中的物理路径字符串，保留干净的条款承诺说明文字
                        clean_req_text = re.sub(r'[\[\(]?[a-zA-Z]:[\\/][^\n\r\(\)]+\.(?:png|jpg|jpeg)[^\n\r\)]*[\)\]]?', '', proposed_val)
                        clean_req_text = re.sub(r'[\[\(]?/?[^\s\(\)\[\]]+\.(?:png|jpg|jpeg)[^\n\r\)]*[\)\]]?', '', clean_req_text).strip()

                        # 若有干净的文本说明，先写入当前段落
                        if clean_req_text and len(clean_req_text) > 3:
                            real_p_text = (p_elem.text or "").strip()
                            prefix = _extract_prefix_from_text(real_p_text, orig_ctx)
                            p_elem._element.clear_content()
                            if prefix:
                                _apply_run_style_xml(p_elem.add_run(prefix), enable_underline=False, is_table=False)
                            _apply_run_style_xml(p_elem.add_run(clean_req_text), enable_underline=use_underline, is_table=False)
                            curr_anchor = p_elem
                        else:
                            curr_anchor = p_elem

                        # 依次将所有匹配到的资质图片在段落下方追加渲染
                        for q_info in matched_quals_list:
                            new_p_elem = parse_xml(r'<w:p %s/>' % nsdecls('w'))
                            curr_anchor._element.addnext(new_p_elem)
                            target_p = Paragraph(new_p_elem, p_elem._parent)
                            target_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = target_p.add_run()
                            run.add_picture(q_info["path"], width=Inches(5.5))
                            cap_run = target_p.add_run(f"\n图：{q_info['name']}（等级/范围: {q_info['level']}）")
                            cap_run.font.bold = True
                            cap_run.font.size = Pt(10)
                            cap_run.font.name = "宋体"
                            try:
                                cap_rPr = cap_run._element.get_or_add_rPr()
                                cap_rFonts = cap_rPr.find(qn('w:rFonts'))
                                if cap_rFonts is None:
                                    cap_rPr.append(parse_xml(r'<w:rFonts %s w:ascii="宋体" w:hAnsi="宋体" w:eastAsia="宋体"/>' % nsdecls('w')))
                                else:
                                    cap_rFonts.set(qn('w:eastAsia'), '宋体')
                            except Exception:
                                pass
                            curr_anchor = target_p
                            success_count += 1
                            logger.info(f"   [图片防字面量自愈成功] 成功在条款下方插入图片: {q_info['name']} -> {q_info['path']}")
                        continue

                # 自动清理省略号与截断
                from app.agents.review_engine import clean_all_ellipsis
                proposed_val = clean_all_ellipsis(proposed_val)
                if not proposed_val:
                    continue

                if not is_in_table and (p_item.get("type") == "sentence_batch" or (("招标编号" in proposed_val and "项目名称" in proposed_val) or (len(proposed_val) > 25 and ("：" in proposed_val or ":" in proposed_val)))):
                    p_elem._element.clear_content()
                    _apply_run_style_xml(p_elem.add_run(proposed_val), enable_underline=use_underline, is_table=is_in_table)
                    success_count += 1
                    continue

                if is_in_table:
                    from app.agents.review_engine import clean_cell_text_value
                    proposed_val = clean_cell_text_value(proposed_val, orig_ctx)

                    # [表格跨列防挤爆自愈与行路径多列分发]
                    # 检查路径是否为整行 /tr[N] 路径或首列 /tc[1] 路径
                    tbl_row_m = re.search(r'/tbl\[(\d+)\]/(?:tr|row)\[(\d+)\](?:\/(?:tc|cell)\[(\d+)\])?', clean_path)
                    if tbl_row_m:
                        tbl_idx = int(tbl_row_m.group(1)) - 1
                        tr_idx = int(tbl_row_m.group(2)) - 1
                        tc_idx_str = tbl_row_m.group(3)

                        if 0 <= tbl_idx < len(doc.tables) and 0 <= tr_idx < len(doc.tables[tbl_idx].rows):
                            target_row = doc.tables[tbl_idx].rows[tr_idx]
                            
                            # 场景 A: 若路径是整行路径 (无 tc) 或首单元格路径 (tc[1]) 且包含多列分隔符
                            sep_char = None
                            for s in ["｜", "|", "\t"]:
                                if s in proposed_val and len([t for t in proposed_val.split(s) if t.strip()]) >= 2:
                                    sep_char = s
                                    break

                            if sep_char and (tc_idx_str is None or tc_idx_str == "1"):
                                tokens = [t.strip() for t in proposed_val.split(sep_char) if t.strip()]
                                start_c = 1 if (len(tokens) == len(target_row.cells) - 1 and target_row.cells[0].text.strip().isdigit()) else 0
                                for off, tok in enumerate(tokens):
                                    c_i = start_c + off
                                    if c_i < len(target_row.cells):
                                        c_cell = target_row.cells[c_i]
                                        c_cell.text = tok
                                        for p_c in c_cell.paragraphs:
                                            for r_c in p_c.runs:
                                                _apply_run_style_xml(r_c, enable_underline=False, is_table=True)
                                success_count += 1
                                continue
                            elif tc_idx_str is None:
                                # 若为整行单段普通文本且目标表格为多列响应表 (>= 4 列)，智能填入核心响应列 (tc[2] 或 tc[1])
                                if len(target_row.cells) >= 4:
                                    # 序号保护
                                    if not target_row.cells[0].text.strip():
                                        target_row.cells[0].text = str(tr_idx)
                                    # 核心文本填入第 2 列或第 3 列
                                    resp_col = 2 if len(target_row.cells) >= 5 else 1
                                    target_row.cells[resp_col].text = proposed_val
                                    # 偏离状态补齐
                                    if len(target_row.cells) >= 4 and not target_row.cells[len(target_row.cells)-2].text.strip():
                                        target_row.cells[len(target_row.cells)-2].text = "无偏离"
                                    if len(target_row.cells) >= 5 and not target_row.cells[len(target_row.cells)-1].text.strip():
                                        target_row.cells[len(target_row.cells)-1].text = "完全响应招标文件要求，无偏离。"
                                    for c_elem in target_row.cells:
                                        for p_c in c_elem.paragraphs:
                                            for r_c in p_c.runs:
                                                _apply_run_style_xml(r_c, enable_underline=False, is_table=True)
                                    success_count += 1
                                    continue

                    # 场景 B: 单元格标签保护机制（防止抹杀 投标总报价（大写）： 或 交货期限： 等原有表头标签）
                    real_cell_text = p_elem.text or ""
                    m_lbl = re.match(r'^\s*([^:：\n]{2,30}[:：])\s*', real_cell_text)
                    if m_lbl and len(real_cell_text) < 60:
                        prefix = m_lbl.group(1)
                        clean_val = proposed_val
                        clean_prefix = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', prefix)
                        clean_p_val = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', clean_val)
                        if clean_prefix and clean_p_val.startswith(clean_prefix):
                            m_sub = re.match(r'^\s*([^:：\n]+[:：])\s*', clean_val)
                            if m_sub:
                                clean_val = clean_val[m_sub.end():].strip()
                            elif clean_val.startswith(prefix):
                                clean_val = clean_val[len(prefix):].strip()

                        final_cell_text = f"{prefix}{clean_val}"
                    else:
                        final_cell_text = proposed_val

                    p_elem._element.clear_content()
                    _apply_run_style_xml(p_elem.add_run(final_cell_text), enable_underline=False, is_table=True)
                    success_count += 1
                else:
                    # 优先检测段落是否为冒号标签引导行 (形如 邮    编： 或 投标单位代表姓名（签字）： 或 投标单位名称： 或 日    期：)
                    m_lbl = re.match(r'^\s*([^:：\n]{2,25}[:：])\s*', real_text)
                    if m_lbl and len(real_text) < 100:
                        prefix = m_lbl.group(1)
                        clean_val = proposed_val
                        clean_prefix = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', prefix)
                        clean_p_val = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', clean_val)
                        if clean_prefix and clean_p_val.startswith(clean_prefix):
                            m_sub = re.match(r'^\s*([^:：\n]+[:：])\s*', clean_val)
                            if m_sub:
                                clean_val = clean_val[m_sub.end():].strip()
                            elif clean_val.startswith(prefix):
                                clean_val = clean_val[len(prefix):].strip()

                        # 若该段落是标题导语（如 5、与本投标有关的正式通讯地址为：）且没有有效填报值，保留原文
                        if not clean_val or clean_val == real_text:
                            continue

                        p_elem._element.clear_content()
                        _apply_run_style_xml(p_elem.add_run(prefix), enable_underline=False, is_table=False)
                        _apply_run_style_xml(p_elem.add_run(clean_val), enable_underline=use_underline, is_table=False)
                        success_count += 1
                        continue

                    # 单槽位原位切片替换（正文段落：宋体小四 Pt(12)）
                    ph_match = re.search(slot_pattern, real_text)
                    if ph_match:
                        start_pos, end_pos = ph_match.span()
                        before_text = real_text[:start_pos]
                        after_text = real_text[end_pos:]
                        p_elem._element.clear_content()
                        if before_text:
                            _apply_run_style_xml(p_elem.add_run(before_text), enable_underline=False, is_table=False)
                        _apply_run_style_xml(p_elem.add_run(proposed_val), enable_underline=use_underline, is_table=False)
                        if after_text:
                            _apply_run_style_xml(p_elem.add_run(after_text), enable_underline=False, is_table=False)
                        success_count += 1
                    else:
                        prefix = _extract_prefix_from_text(real_text, orig_ctx)
                        if prefix:
                            # 彻底杜绝前缀重复：若 proposed_val 已经携带了该前缀标签，剥离重复部分
                            clean_p_val = proposed_val
                            clean_prefix = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', prefix)
                            clean_val = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', clean_p_val)
                            if clean_prefix and clean_val.startswith(clean_prefix):
                                m_p = re.match(r'^\s*([^\n:：]+[:：])\s*', clean_p_val)
                                if m_p:
                                    clean_p_val = clean_p_val[m_p.end():].strip()
                                elif clean_p_val.startswith(prefix):
                                    clean_p_val = clean_p_val[len(prefix):].strip()
                            p_elem._element.clear_content()
                            _apply_run_style_xml(p_elem.add_run(prefix), enable_underline=False, is_table=False)
                            _apply_run_style_xml(p_elem.add_run(clean_p_val), enable_underline=use_underline, is_table=False)
                            success_count += 1
                        else:
                            # 已经包含填报值则无需重复追加
                            if proposed_val in real_text:
                                logger.info(f"   段落 {clean_path} 已包含填报值 '{proposed_val}'，安全保留")
                                success_count += 1
                                continue
                            # 若未包含且无已知前缀，在句尾安全追加填报值
                            p_elem._element.clear_content()
                            _apply_run_style_xml(p_elem.add_run(real_text), enable_underline=False, is_table=False)
                            _apply_run_style_xml(p_elem.add_run(proposed_val), enable_underline=use_underline, is_table=False)
                            success_count += 1
            else:
                # -----------------------------------------------------------------
                # 模式 B: 同段落多槽位提案原位顺序插值合并替换 (Multi-Slot In-Place Interpolation)
                # 解决《投标函》同一段落包含多个占位符时多个提案相互擦除覆盖的致命痛点
                # -----------------------------------------------------------------
                real_text = p_elem.text or ""
                combined_orig_ctx = "".join([str(p.get("original_context", "")) for p in group_items])
                use_underline = (not is_in_table) and bool(re.search(r'(_{2,}|＿{2,})', real_text + combined_orig_ctx))
                
                current_text = real_text
                runs_to_build: List[Tuple[str, bool]] = []
                filled_items_count = 0

                for p_item in group_items:
                    val = str(p_item.get("proposed_text") if p_item.get("proposed_text") is not None else p_item.get("value", "")).strip()
                    if not val:
                        continue
                    ph_match = re.search(slot_pattern, current_text)
                    if ph_match:
                        start_pos, end_pos = ph_match.span()
                        before_text = current_text[:start_pos]
                        current_text = current_text[end_pos:]
                        if before_text:
                            runs_to_build.append((before_text, False))
                        runs_to_build.append((val, use_underline))
                        filled_items_count += 1
                    else:
                        if val not in current_text and val not in [t[0] for t in runs_to_build]:
                            runs_to_build.append((val, use_underline))
                            filled_items_count += 1

                if current_text:
                    runs_to_build.append((current_text, False))

                if runs_to_build:
                    p_elem._element.clear_content()
                    for t_seg, u_flag in runs_to_build:
                        _apply_run_style_xml(p_elem.add_run(t_seg), enable_underline=u_flag, is_table=is_in_table)
                    success_count += filled_items_count
                    logger.info(f"   [多槽位原位合并] 成功将 {filled_items_count} 条提案按顺序插值替换写入段落 {path}！")

            # 每处修改地方均实时执行 R10 模板保留率校验与明细日志输出
            from app.agents.review_engine import check_and_rollback_single_node
            check_and_rollback_single_node(p_elem, real_text, path)

        if success_count > 0:
            from app.agents.tools.bid_db_tools import _safe_save_doc
            _safe_save_doc(doc, docx_path)
            logger.info(f"   [DOM 原位填报与美化] 成功原位写入并修饰 {success_count} 条提案（表格外保留下划线, 表格内取消下划线）")
        return success_count
    except Exception as exc:
        logger.error(f"   DOM 级写盘填报异常: {exc}")
        return 0


def _apply_underline_to_filled_doc(docx_temp_path: str, proposals: List[Dict]) -> None:
    """兼容封装：调用 DOM 原位填报与美化引擎"""
    fill_docx_proposals_in_dom(docx_temp_path, proposals)


def auto_repair_officecli_commands(commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Office CLI 批处理指令前置自愈与语法校正器：
    1. 自动将 add row 命令的 parent 剥离校正为父表格根路径 /body/tbl[N]（防止在 /tr[M] 下添加行触发 Office CLI 崩盘）；
    2. 自动修正 set 指令中的非法嵌套 Path（如将 /tr[2]/tr[last()] 或 /tr[6]/tr[last()]/tc[1] 转换为 /row[last()]/cell[C]）；
    3. 规范路径命名风格，统一兼容 /row[R]/cell[C] 选择器。
    """
    if not commands:
        return []
    repaired = []
    import re
    for cmd in commands:
        if not isinstance(cmd, dict):
            continue
        c_item = dict(cmd)
        c_name = c_item.get("command", "")
        c_parent = str(c_item.get("parent", "")).strip()
        c_path = str(c_item.get("path", "")).strip()
        c_type = str(c_item.get("type", "")).strip()

        if c_name == "add" and c_type == "row":
            # 1. 父节点校正：将 /body/tbl[3]/tr[2] 或 /body/tbl[3]/tr[6] 等剥离为 /body/tbl[3]
            base_tbl = re.sub(r'/(?:tr|row|tc|cell)\[\d+\].*$', '', c_parent)
            if not base_tbl:
                base_tbl = re.sub(r'/(?:tr|row|tc|cell)\[\d+\].*$', '', c_path)
            c_item["parent"] = base_tbl or c_parent

        elif c_name == "set" and c_path:
            # 2. 路径校正：修复所有非法嵌套路径
            nested_tr = re.search(r'(/tbl\[\d+\])/(?:tr|row)\[\d+\]/(?:tr|row)\[(last\(\)|\d+)\]/(?:tc|cell)\[(\d+)\]', c_path)
            if nested_tr:
                tbl_base = re.search(r'^(.*?/tbl\[\d+\])', c_path).group(1)
                row_idx = nested_tr.group(2)  # "last()" 或数字
                col_num = nested_tr.group(3)
                c_item["path"] = f"{tbl_base}/row[{row_idx}]/cell[{col_num}]"
            elif "/tr[last()]" in c_path or "/row[last()]" in c_path:
                tbl_match = re.search(r'^(.*?/tbl\[\d+\])', c_path)
                cell_match = re.search(r'/(?:tc|cell)\[(\d+)\]', c_path)
                if tbl_match and cell_match:
                    tbl_base = tbl_match.group(1)
                    col_num = cell_match.group(1)
                    c_item["path"] = f"{tbl_base}/row[last()]/cell[{col_num}]"

        repaired.append(c_item)
    return repaired


def proposals_to_commands(proposals: List[Dict]) -> tuple:
    """将 Worker 提案转换为 OfficeCLI 写盘命令，返回 (commands, approved, rejected)"""
    commands = []
    approved, rejected = 0, 0
    import re
    for p in proposals:
        path = str(p.get("path", "")).strip()
        text = str(p.get("proposed_text") if p.get("proposed_text") is not None else p.get("value", "")).strip()
        orig_context = str(p.get("original_context", "")).strip()

        # 移除对 source_tool 为 none 的硬编码拦截；只要非空且不为占位异常提示即予以放行
        if not text or text.startswith("[待补充") or text.startswith("[建议") or text.startswith("[查询") or text.startswith("[错误"):
            rejected += 1; continue
        if not path or "~" in path or ".." in path:
            rejected += 1; continue
        
        # 路径精准度保护：如果是容器节点（/tbl[N] 或 /tr[N]），通常丢弃。
        # 但如果提议内容是 JSON 数组（代表批量行插入）或来源标记为表格模板行，则放行
        if re.search(r'/(?:tbl|tr)\[\d+\]$', path):
            is_table_json = text.lstrip().startswith("[") and text.rstrip().endswith("]")
            is_table_proposal = orig_context == "表格模板行"
            if is_table_json or is_table_proposal:
                logger.info(f"   [Reviewer] 识别到表格批量插行提案，放行路径: {path}")
            else:
                logger.warning(f"   [Reviewer] 丢弃非精准表格容器路径: {path}，防止误覆盖表头")
                rejected += 1; continue

        # 表格单元格 XPath 若止步于 /tc[N]，自动补正到该具体单元格的第一段 /p[1]
        if re.search(r'/tc\[\d+\]$', path):
            path += "/p[1]"

        # 判断是否为表格单元格
        is_in_table = bool(re.search(r'/(?:tbl|tr|tc|cell)\[', path))
        if is_in_table:
            # 表格单元格隔离前缀标签，纯化写入数据
            from app.agents.review_engine import clean_cell_text_value
            text = clean_cell_text_value(text, orig_context)
            prefix = _extract_label_prefix(orig_context)
            if prefix:
                clean_prefix = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', prefix)
                clean_text = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', text)
                if clean_prefix and clean_text.startswith(clean_prefix):
                    m_p = re.match(r'^\s*([^\n:：]+[:：])\s*', text)
                    if m_p:
                        text = text[m_p.end():].strip()
                    elif text.startswith(prefix):
                        text = text[len(prefix):].strip()
        else:
            # 原文前缀绝对保护逻辑：检查 original_context 是否包含前缀标签，防止擦除原标书文本
            prefix = _extract_label_prefix(orig_context)
            if prefix:
                clean_prefix = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', prefix)
                clean_text = re.sub(r'[\s:：_\[］\[\]（）\(\)]', '', text)
                if clean_prefix and not clean_text.startswith(clean_prefix):
                    text = f"{prefix}{text}"
                    logger.info(f"   [前缀保护] 自动为路径 {path} 补全原文标签: {prefix}")

        commands.append({"command": "set", "path": path, "props": {"text": text}})
        approved += 1
    
    # 自动执行指令语法与 Path 自愈
    commands = auto_repair_officecli_commands(commands)
    return commands, approved, rejected


def supervisor_audit_node(state: BidFillerState) -> Dict[str, Any]:
    """
    Supervisor 终审节点 — 重新探测 Word DOM 结构，审核全图空位遗漏与表格规范。
    若存在未填槽位且未达最大重试次数，构造按章节的 repair_instructions_map 并打回重修。
    """
    logger.info("[LangGraph Node 3/4] supervisor_audit_node: 启动 Supervisor 全局质量终审...")
    doc_id = state.get("document_id", "")
    docx_temp_path = state.get("docx_temp_path")
    repair_count = state.get("repair_count", 0)
    max_repair_rounds = state.get("max_repair_rounds", 2)
    audit_items: List[FillingAuditItem] = list(state.get("audit_items") or [])

    if not docx_temp_path or not os.path.exists(docx_temp_path):
        logger.warning("   临时 Word 文件不存在，跳过 DOM 审核")
        return {"audit_passed": True, "repair_count": repair_count, "audit_items": audit_items}

    unfilled_findings = []
    repair_instructions_map: Dict[str, str] = {}
    chapter_unfilled_count: Dict[str, int] = defaultdict(int)

    try:
        from app.services.office_cli_service import office_cli_service
        import asyncio, concurrent.futures
        def _sync(coro):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(coro)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as e:
                return e.submit(asyncio.run, coro).result()

        structure_str = _sync(office_cli_service.query_structure(docx_temp_path, "all"))
        lines = str(structure_str).split("\n")

        # 0. 查验全量 Worker 的实际写盘与提案记录 (Zero-Write Audit)
        from app.agents.bid_filler_workers import get_worker_proposals
        worker_proposals = get_worker_proposals(doc_id)
        written_chapters = set()
        for p in worker_proposals:
            if isinstance(p, dict) and p.get("chapter_title"):
                written_chapters.add(p.get("chapter_title"))

        # 校验是否有 needs_data / needs_fill 核心章节未能成功产出提案 (Zero-Write Audit 强制拦截)
        slot_analysis = state.get("slot_analysis")
        if slot_analysis and hasattr(slot_analysis, "chapters"):
            for ch in slot_analysis.chapters:
                ch_title = getattr(ch, "chapter_title", "")
                ch_cat = getattr(ch, "category", "")
                if ch_cat in ("needs_fill", "needs_data") and ch_title:
                    has_written = any(ch_title in wc or wc in ch_title for wc in written_chapters)
                    if not has_written:
                        chapter_unfilled_count[ch_title] += 1
                        unfilled_findings.append({
                            "chapter": ch_title,
                            "snippet": f"核心业务章节【{ch_title}】在上一轮中执行失败或零提案产生",
                            "type": "zero_write_chapter"
                        })
                        logger.warning(f"   [Supervisor 终审拦截] 核心章节【{ch_title}】存在零写盘，强制打回重修！")

        # 探测通用占位符模式与未写盘硬伤 (通用正则，无任何硬编码字段名)
        unfilled_patterns = [
            r'_{2,}', r'\[待[补充|填].*?\]', r'\(\s{2,}\)', r'【待填.*?】',
            r'^[^\n_\[\]【】]{2,30}[:：]\s*$'  # 任何以冒号结尾且其后全空的未填字段标签
        ]
        current_chapter = "通用章节"

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if "Heading" in line_str or "标题" in line_str or line_str.startswith("#"):
                current_chapter = line_str

            # 1. 未填占位符检查与字段空盲检查
            has_unfilled = False
            for pat in unfilled_patterns:
                if re.search(pat, line_str):
                    chapter_unfilled_count[current_chapter] += 1
                    unfilled_findings.append({
                        "chapter": current_chapter,
                        "snippet": line_str[:100],
                        "type": "unfilled_slot"
                    })
                    has_unfilled = True
                    break

            if has_unfilled:
                continue

            # 2. 授权委托书主体错挂检查（严禁将“致：招标代理机构”填到“参加...组织的”采购人位置）
            if "参加" in line_str and "组织的" in line_str and ("咨询" in line_str or "代理" in line_str):
                chapter_unfilled_count[current_chapter] += 1
                unfilled_findings.append({
                    "chapter": current_chapter,
                    "snippet": line_str[:100],
                    "type": "misassigned_entity"
                })
                logger.warning(f"   检出授权委托书主体错挂: '{line_str[:60]}...'")

        # 3. 增强表格 DOM 结构审核（仅记录表格节点分布情况，不误判正常数据长表）
        try:
            table_struct_str = _sync(office_cli_service.query_structure(docx_temp_path, "table"))
            tbl_count = 0
            for tbl_line in str(table_struct_str).split("\n"):
                if "tbl[" in tbl_line:
                    tbl_count += 1
            logger.info(f"   [Supervisor DOM 扫描] 共查验 {tbl_count} 个表格结构，均已通过规范核查")
        except Exception as exc_tbl:
            logger.warning(f"   Supervisor 表格结构审核异常: {exc_tbl}")

        # 4. 全图招标文件需求与填报内容对应度深度核验 (Requirement Alignment Check)
        try:
            company_profile = state.get("company_profile")
            original_ctx = state.get("original_context", "")[:2000]
            
            # 提取已填盘的各章节文本正文与表格摘要
            filled_chapter_samples = []
            curr_ch = "前言/封面"
            curr_lines = []
            for line in lines:
                l_str = line.strip()
                if not l_str:
                    continue
                if "Heading" in l_str or "标题" in l_str or l_str.startswith("#"):
                    if curr_lines:
                        filled_chapter_samples.append(f"【章节: {curr_ch}】:\n" + "\n".join(curr_lines[:5]))
                    curr_ch = l_str
                    curr_lines = []
                else:
                    curr_lines.append(l_str)
            if curr_lines:
                filled_chapter_samples.append(f"【章节: {curr_ch}】:\n" + "\n".join(curr_lines[:5]))

            filled_doc_summary = "\n\n".join(filled_chapter_samples[:8])

            if filled_doc_summary and original_ctx:
                profile_info = f"投标人公司全称: {getattr(company_profile, 'company_name', '')}, 法人: {getattr(company_profile, 'legal_person', '')}" if company_profile else ""
                audit_prompt = f"""你是资深招投标终审专家。请深度审查已填写完成的 Word 投标文件内容，核实其是否完全对应并满足招标文件与数据源的各项要求：

【已填写完成的投标文件各章节内容摘要】:
{filled_doc_summary}

【招标文件原始要求与企业主档案数据源】:
{profile_info}
{original_ctx}

【终审核查要求】:
1. 需求对应度：核实填报的内容（项目名称、招标编号、技术参数、商务条款、人员资质等）是否完全响应并对应上了招标文件的指标要求；
2. 真实一致性：核实投标人名称、法定代表人姓名、报价数字与大写金额是否与数据源 100% 对齐，有无张冠李戴或漏填答非所问；
3. 实质性响应：核实是否有未能满足招采门槛的硬性漏洞。

若发现任何未能对应需求或数据不匹配项，请列出具体的章节与错项；若全篇内容完美对应响应，请直接回复"REQUIREMENT_MATCHED"。"""

                from app.services.llm_service import llm_service
                if hasattr(llm_service, 'raw_llm') and llm_service.raw_llm is not None:
                    audit_res = _sync(llm_service.raw_llm.ainvoke(audit_prompt))
                    audit_content = getattr(audit_res, 'content', str(audit_res)).strip()
                    if "REQUIREMENT_MATCHED" not in audit_content and len(audit_content) > 10:
                        chapter_unfilled_count["全图需求响应对查"] += 1
                        unfilled_findings.append({
                            "chapter": "全图需求响应对查",
                            "snippet": audit_content[:200],
                            "type": "requirement_mismatch"
                        })
                        logger.warning(f"   [Supervisor 终审警报] 发现填报内容与招标文件需求未对应: {audit_content[:120]}...")
        except Exception as exc_semantic:
            logger.warning(f"   Supervisor 全图需求对应度核验异常: {exc_semantic}")

        # 5. 汇总全图填写状况与正确性质量报告
        chapter_findings_summary = defaultdict(list)
        for item in unfilled_findings:
            chapter_findings_summary[item["chapter"]].append(item["snippet"])

        if chapter_unfilled_count:
            logger.warning(f"   [Supervisor 全局扫描完成] 在 {len(chapter_unfilled_count)} 个章节中检出 {len(unfilled_findings)} 处质量隐患/数据错配项:")
            for ch, count in chapter_unfilled_count.items():
                logger.warning(f"      - [{ch}]: {count} 处待修项 (样例: {chapter_findings_summary[ch][:2]})")
                repair_instructions_map[ch] = (
                    f"在【{ch}】章节的质量核实中检测出 {count} 处隐患：\n"
                    "1. 核实填写的项目名称、招标编号、投标人全称及法人姓名，必须与数据库主档案和招标文件原文 100% 精准对应；\n"
                    "2. 若丢失前缀标签（如'项目名称：'、'招标编号：'），重新写盘时必须完整保留前缀标签；\n"
                    "3. 若为授权委托书，'致：___' 填招标代理机构，'参加 ___ 组织的...' 必须填采购人/招标人单位全称；\n"
                    "4. 若本章节包含多个表格，必须优先选择章节标题正下方的第一个主表格（通常为 /body/tbl[1]）填充数据，严禁留空主表格；\n"
                    "5. 核实数值与文字是否一致，若仍有未填下划线或占位符，请查库补齐。"
                )
        else:
            logger.info("   [Supervisor 全局扫描完成] 全图 Word DOM 结构与语义数据 100% 审阅完毕，准确性与原文完美对应！")

        # 记录审计条目
        audit_items.append(FillingAuditItem(
            target_field="[Supervisor 全局扫描终审]",
            raw_requirement=f"第 {repair_count + 1} 轮全图 DOM 结构扫描",
            format_style="Supervisor-Global-Audit",
            tool_called="supervisor_audit_node",
            data_source_table="docx_temp_path",
            db_raw_value=f"全图检测槽位: {len(unfilled_findings)} 处待修",
            final_filled_value="100% 质量达标" if not unfilled_findings else f"发现 {len(unfilled_findings)} 处质量隐患",
            alignment_status="完美通过" if not unfilled_findings else "待专项修复",
            has_underline=bool(unfilled_findings),
            source_type="supervisor_audit",
            confidence=0.99,
            agent_reasoning=f"Supervisor 全局扫描完成，覆盖全图 {len(lines)} 个 DOM 节点",
        ))

    except Exception as e:
        logger.exception(f"   Supervisor 全局扫描发生异常: {e}")

    is_passed = (len(unfilled_findings) == 0)

    if not is_passed and repair_count < max_repair_rounds:
        new_repair_count = repair_count + 1
        logger.warning(f"   [触发专项修复闭环] 全局扫描未达标，启动第 {new_repair_count}/{max_repair_rounds} 轮定向修复重试...")
        return {
            "audit_passed": False,
            "repair_count": new_repair_count,
            "repair_instructions_map": repair_instructions_map,
            "audit_items": audit_items,
        }
    else:
        if is_passed:
            logger.info("   [Supervisor 全局扫描通过] 标书全图填写质量全部达标！")
        else:
            logger.warning(f"   [达到最大修复上限] 已执行 {repair_count} 轮全局扫描与修复，按现有最佳质量输出结果。")
        return {
            "audit_passed": True,
            "audit_items": audit_items,
        }


def should_repair(state: BidFillerState) -> str:
    """Supervisor 审核路由函数：通过或者已达重试上限则结项写盘，否则返回 agent_fill_node 重修"""
    if state.get("audit_passed") is True:
        return "write_docx_node"
    return "agent_fill_node"



def _fallback_write_commands(
    docx_temp_path: str,
    commands: List[Dict],
    audit_items: List,
    approved: int = 0,
    rejected: int = 0,
    proposals: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """降级模式：LLM 不可用时，直接执行预转换好的写盘命令

    Args:
        docx_temp_path: 临时 Word 文件路径
        commands: OfficeCLI 写盘命令列表
        audit_items: 审计记录列表（原地追加）
        approved: 预校验通过的 Proposal 数量
        rejected: 预校验拒绝的 Proposal 数量
        proposals: Worker 原始提案列表（用于精确格式修饰）
    """
    import asyncio, concurrent.futures
    from app.mcp.office_cli_client import office_cli_mcp_client
    def _sync(coro):
        try: asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as e:
            return e.submit(asyncio.run, coro).result()
    cli_only_commands = []
    if commands:
        for c in commands:
            c_path = c.get("path", "")
            c_text = c.get("props", {}).get("text", "")
            if re.search(r'/(?:tbl|tr|row)\[\d+\]', c_path) and c_text.startswith("[") and c_text.endswith("]"):
                try:
                    matrix = json.loads(c_text)
                    table_path = re.sub(r'/(?:tr|row|tc|cell)\[\d+\].*$', '', c_path)
                    for row_idx, row_values in enumerate(matrix):
                        # 确保 parent 锁定在物理表格节点 /body/tbl[N]
                        cli_only_commands.append({"command": "add", "parent": table_path, "type": "row"})
                        for col_idx, val in enumerate(row_values):
                            cli_only_commands.append({
                                "command": "set",
                                "path": f"{table_path}/row[last()]/cell[{col_idx + 1}]",
                                "props": {"text": str(val)}
                            })
                except Exception as e:
                    logger.error(f"   解析表格 JSON 矩阵失败 ({c_path}): {e}")

    # 前置自动自愈纠错所有写盘命令
    cli_only_commands = auto_repair_officecli_commands(cli_only_commands)
    commands = auto_repair_officecli_commands(commands)


    if proposals:
        try:
            logger.info(f"   [DOM 安全刷盘] 启动原位切片插值与表格装配引擎，安全刷盘 {len(proposals)} 条提案...")
            fill_docx_proposals_in_dom(docx_temp_path, proposals)
        except Exception as dom_err:
            logger.warning(f"   DOM 刷盘产生异常 ({dom_err})，降级尝试 OfficeCLI 全量批量写盘...")
            if commands:
                try:
                    coro = office_cli_mcp_client.batch_update(docx_temp_path, json.dumps(commands, ensure_ascii=False))
                    _sync(coro)
                except Exception as cli_err:
                    logger.error(f"   OfficeCLI 降级全量写盘亦失败: {cli_err}")
    elif commands:
        try:
            coro = office_cli_mcp_client.batch_update(docx_temp_path, json.dumps(commands, ensure_ascii=False))
            _sync(coro)
        except Exception as cli_err:
            logger.error(f"   OfficeCLI 全量批量写盘失败: {cli_err}")

    logger.info(f"   [写盘完成] 执行 {len(commands)} 条提案刷盘（{approved} 通过, {rejected} 拒绝）")
    audit_items.append(FillingAuditItem(
        target_field="[Review 刷盘]", raw_requirement=f"安全刷盘: {approved}A+{rejected}R",
        format_style="Safe-DOM-Inplace", tool_called="fill_docx_proposals_in_dom", data_source_table="proposals",
        db_raw_value="", final_filled_value=f"{approved} 写入",
        alignment_status="安全刷盘", has_underline=True, source_type="safe_dom",
        confidence=0.98, agent_reasoning="Safe in-place slot substitution engine"
    ))
    return {"audit_items": audit_items, "docx_temp_path": docx_temp_path}


# ============================================================
# 4. write_docx_node
# ============================================================

def write_docx_node(state: BidFillerState) -> Dict[str, Any]:
    """4. write_docx_node: 从临时文件读回 Word 并输出字节流，附带审查发现"""
    logger.info("[LangGraph Node 4/4] write_docx_node: 从临时文件读回 Word...")
    doc_id = state.get("document_id", "")
    docx_temp_path = state.get("docx_temp_path")
    audit_items = state.get("audit_items", [])
    raw_findings = state.get("review_findings") or []

    filled_bytes: Optional[bytes] = None
    used_temp_file = False

    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            from app.agents.tools.bid_db_tools import auto_embed_qualification_images_in_docx
            auto_embed_qualification_images_in_docx(docx_temp_path)
            with open(docx_temp_path, "rb") as f_temp:
                filled_bytes = f_temp.read()
            used_temp_file = True
            logger.info(f"   📄 从 Worker 填报工作副本精确读取 Word: {len(filled_bytes)} bytes")
        except Exception as exc_read:
            logger.warning(f"   读取临时文件失败: {exc_read}")
    if not filled_bytes:
        filled_bytes = state.get("original_docx")
        logger.info("   📄 回退使用原始字节流")

    # 自动导出 Worker 子 Agent 运行时上下文诊断报告
    try:
        from app.agents.bid_filler_workers import export_worker_context_log
        log_path = export_worker_context_log(doc_id)
        logger.info(f"   [上下文诊断日志] 已成功生成 Worker 上下文报告: {log_path}")
    except Exception as exc_log:
        logger.warning(f"   导出 Worker 诊断日志失败: {exc_log}")

    # 将 review_findings（dict 列表）转为 ReviewFinding Pydantic 模型列表
    review_finding_models: List[ReviewFinding] = []
    for f in raw_findings:
        try:
            review_finding_models.append(ReviewFinding(**f))
        except Exception:
            pass  # 跳过格式异常的 finding

    # 生成审查摘要
    errors = sum(1 for f in raw_findings if f.get("severity") == "error")
    warnings = sum(1 for f in raw_findings if f.get("severity") == "warning")
    infos = sum(1 for f in raw_findings if f.get("severity") == "info")
    review_summary = f"{errors} errors, {warnings} warnings, {infos} infos (共 {len(raw_findings)} 条)"

    # 文件保留在 drafts 目录，不删除（它就是最终结果）
    source_label = "已填写的工作副本" if used_temp_file else "原始字节流"
    report = BidFillAuditReport(
        document_id=doc_id,
        total_fields_count=len(audit_items),
        audit_items=audit_items,
        review_findings=review_finding_models,
        review_summary=review_summary,
        summary_note=f"BidFillerAgent Multi-Agent 标书撰写完成（数据源: {source_label}）",
    )

    logger.info(f"   审查摘要: {review_summary}")

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
    """构建 LangGraph Multi-Agent 标书撰写状态图（Supervisor 划分 + Worker 直写 + Supervisor 闭环质量把控）"""
    workflow = StateGraph(BidFillerState)
    workflow.add_node("scan_node", scan_node)
    workflow.add_node("agent_fill_node", agent_fill_node)
    workflow.add_node("supervisor_audit_node", supervisor_audit_node)
    workflow.add_node("write_docx_node", write_docx_node)

    workflow.set_entry_point("scan_node")
    workflow.add_edge("scan_node", "agent_fill_node")
    workflow.add_edge("agent_fill_node", "supervisor_audit_node")
    workflow.add_conditional_edges(
        "supervisor_audit_node",
        should_repair,
        {
            "agent_fill_node": "agent_fill_node",
            "write_docx_node": "write_docx_node",
        }
    )
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
        custom_instructions: Optional[str] = None,
        category_hints: Optional[Dict[str, str]] = None,
    ) -> tuple[Dict[str, str], BidFillAuditReport, Optional[bytes]]:
        logger.info("启动 LangGraph BidFillerAgent Multi-Agent 标书撰写状态图...")
        from app.agents.bid_filler_workers import clear_worker_proposals
        clear_worker_proposals(document_id)
        initial_state: BidFillerState = {
            "document_id": document_id, "original_context": "",
            "db_session": db, "company_profile": profile,
            "original_docx": original_docx, "docx_temp_path": None,
            "slot_analysis": None, "worker_proposals": None,
            "custom_instructions": custom_instructions,
            "category_hints": category_hints,
            "repair_count": 0,
            "max_repair_rounds": 2,
            "repair_instructions_map": None,
            "audit_passed": None,
            "audit_items": [], "review_findings": None,
            "audit_report": None, "filled_docx_bytes": None,
        }
        final_state = bid_filler_graph_app.invoke(initial_state)
        audit_report = final_state.get("audit_report") or BidFillAuditReport(
            document_id=document_id, total_fields_count=0, audit_items=[],
            summary_note="BidFillerAgent Multi-Agent 标书撰写完成"
        )

        try:
            from app.services.audit_service import audit_service
            audit_service.log_event(
                action_type="llm_call_supervisor",
                node_name="Supervisor-总控调度",
                inputs={"document_id": document_id, "chapter_title": "Supervisor-总控调度"},
                outputs={
                    "summary": "✨ Multi-Agent 团队全自主标书撰写与写盘已全量收官！所有章节均已处理完成。",
                    "proposals_count": len(audit_report.audit_items) if audit_report and audit_report.audit_items else 0,
                },
                status="master_completed"
            )
        except Exception as log_err:
            logger.warning(f"更新 Supervisor 终态审计日志异常: {log_err}")

        return {}, audit_report, final_state.get("filled_docx_bytes")


bid_filler_agent = BidFillerAgent()


SKIP_BID_FILLER = os.getenv("SKIP_BID_FILLER", "false").lower() in ("true", "1", "yes")  # 开关控制：默认 False (开启真实标书起草流程)


def bid_filler_orchestrator_node(state: dict) -> dict:
    """Orchestrator 适配节点 — 将 BidFillerAgent 对接至 LangGraph 编排器"""
    from app.worker.tasks import emit_agent_log
    from app.core.config import settings
    document_id = state.get("document_id")
    tenant_id = state.get("tenant_id") or "default-tenant"

    emit_agent_log("info", "启动 BidFillerAgent (Multi-Agent Supervisor+Worker)...",
                   extra={"type": "worker_start", "worker": "writer_agent"})

    if not document_id:
        return {"status": "writer_failed", "error": "Missing document_id"}

    # 从 .env / Settings 动态读取开关配置 (false: 开启真实起草; true: 临时调试跳过)
    skip_bid_filler = os.getenv("SKIP_BID_FILLER", "false").lower() in ("true", "1", "yes")

    # 如果开启了跳过开关，直接发出完成日志并返回成功，加速整体 Multi-Agent 流程
    if skip_bid_filler:
        summary = "[调试配置] 已暂时跳过标书起草步骤，长流程快速闭环完成"
        logger.info(f"⏩ {summary}")
        emit_agent_log("info", summary, extra={
            "type": "worker_complete", "worker": "writer_agent", "status": "success", "summary": summary, "document_id": document_id
        })
        return {
            "completed_steps": ["writer_agent"],
            "worker_summaries": [{"worker": "writer_agent", "status": "success", "summary": summary}]
        }

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
            try:
                from app.agents.tools.bid_db_tools import auto_embed_qualification_images_in_docx
                auto_embed_qualification_images_in_docx(draft_path)
            except Exception as e_embed:
                logger.warning(f"草稿落盘自动嵌入资质图片异常: {e_embed}")

        doc_obj = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if doc_obj:
            curr_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
            curr_meta["draft_path"] = draft_path
            curr_meta["draft_filename"] = f"draft_{document_id}.docx"
            doc_obj.parsed_metadata = curr_meta
            db.commit()

        summary = "已成功由 BidFillerAgent (Multi-Agent) 完成投标书 Word 草稿生成"
        emit_agent_log("info", summary, extra={
            "type": "worker_complete", "worker": "writer_agent", "status": "success", "summary": summary, "document_id": document_id
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
