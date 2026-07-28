"""
BidFillerAgent - 基于 LangGraph 状态图 (StateGraph) 的全自主标书撰写 Agent

架构说明：
1. 显式图状态：基于 TypedDict 定义 BidFillerState 管理撰写生命周期；
2. 3 大状态节点 (Nodes)：
   - scan_node：写入 Word 临时文件供 OfficeCLI 访问 + 提取原文全文上下文；
   - agent_fill_node：LLM ReAct Agent 全自主标书撰写闭环——
     自行阅读 Word 文档结构 → 理解各章节要求 → 查询数据库获取事实 → 组织语言撰写内容 → 通过 OfficeCLI 原位写入 Word；
   - write_docx_node：从临时文件读取 Agent 修改后的 Word 并输出最终字节流。
3. Agent 是标书撰写专家，不是槽位填充工：拿到 DB 数据后自主思考如何遣词造句、如何组织段落。
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
    """LangGraph 全自主标书撰写全局状态 (State)"""
    document_id: str
    original_context: str                                   # 原始 Word 全文上下文（供 Agent 理解文档结构）
    slot_analysis: Optional[List[Dict[str, Any]]]           # LLM Slot Analyzer 预识别的槽位清单（减少 Agent 探索轮次）

    db_session: Any                                         # SQLAlchemy Session
    company_profile: CompanyProfile                         # 企业档案入参
    original_docx: Optional[bytes]                          # 原始 Word 字节流
    docx_temp_path: Optional[str]                           # OfficeCLI MCP 可访问的 Word 临时文件路径

    audit_items: List[FillingAuditItem]                     # 对齐追溯审计条目
    audit_report: Optional[BidFillAuditReport]              # 最终审计报告
    filled_docx_bytes: Optional[bytes]                      # 导出的 Word 字节流


# ============================================================
# LangGraph 3 大 Node 节点实现
# ============================================================

def scan_node(state: BidFillerState) -> Dict[str, Any]:
    """1. scan_node: 写入 Word 临时文件供 OfficeCLI MCP 访问 + 提取全文上下文 + LLM 槽位预识别"""
    logger.info("📍 [LangGraph Node 1/3] scan_node: 写入临时文件、提取全文上下文并预识别槽位...")
    original_docx = state.get("original_docx")
    original_context = ""
    docx_temp_path = None
    slot_analysis: Optional[List[Dict[str, Any]]] = None

    if original_docx:
        # 写入临时文件供 OfficeCLI MCP 工具后续访问
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False, prefix="bid_fill_") as tmp_file:
                tmp_file.write(original_docx)
                docx_temp_path = tmp_file.name
            logger.info(f"   📄 已将 Word 字节流写入临时文件供 OfficeCLI 访问: {docx_temp_path}")
        except Exception as exc_tmp:
            logger.warning(f"   ⚠️ 写入 Word 临时文件失败，OfficeCLI 工具将不可用: {exc_tmp}")

        # 提取全文上下文供 Agent 参考（Agent 自己通过 OfficeCLI 读文档结构，这里只提供文本参考）
        try:
            from app.services.bid_format_filler_service import bid_format_filler_service
            original_context = bid_format_filler_service.extract_original_document_context(original_docx)
            logger.info(f"   📖 已提取 Word 全文上下文 ({len(original_context)} 字符)")
        except Exception as exc:
            logger.warning(f"读取原始 Word 上下文时发生异常（Agent 仍可通过 OfficeCLI 读取）: {exc}")

        # LLM 槽位预识别：通过大模型一次性感知文档中所有待填空槽位，减少 Agent 后续探索 Token 消耗
        try:
            from app.services.llm_slot_analyzer import analyze_slots_with_llm
            slot_report = analyze_slots_with_llm(original_context)
            if slot_report and slot_report.slots:
                slot_analysis = [s.model_dump() for s in slot_report.slots]
                logger.info(f"   🔎 LLM 槽位预识别完成，共发现 {len(slot_analysis)} 个待填槽位")
            else:
                logger.info("   🔎 LLM 槽位预识别：未发现待填槽位")
        except Exception as exc_slot:
            logger.warning(f"   ⚠️ LLM 槽位预识别失败（Agent 仍可自主探索）: {exc_slot}")

    return {
        "original_context": original_context,
        "docx_temp_path": docx_temp_path,
        "slot_analysis": slot_analysis,
    }


def _build_slot_hint(slot_analysis: Optional[List[Dict[str, Any]]]) -> str:
    """将 LLM Slot Analyzer 预识别的槽位清单格式化为 Agent Prompt 提示片段"""
    if not slot_analysis:
        return ""
    lines = [
        "\n【预识别槽位清单 — AI 已提前感知文档中的空白位置（供参考，仍需通过 OfficeCLI 验证确认）】",
        "以下槽位已由系统预识别，你可直接定位并填报：",
    ]
    for idx, s in enumerate(slot_analysis[:30], 1):  # 最多展示 30 个槽位，防止 Prompt 过长
        label = s.get("label", "")
        intent = s.get("target_field_intent", "")
        path = s.get("path", "")
        placeholder = s.get("raw_placeholder", "")
        lines.append(f"  {idx}. [{intent}] {label} → 路径: {path} (占位符: '{placeholder}')")
    if len(slot_analysis) > 30:
        lines.append(f"  ... 还有 {len(slot_analysis) - 30} 个槽位，请通过 OfficeCLI 工具自行探索")
    return "\n".join(lines)


def agent_fill_node(state: BidFillerState) -> Dict[str, Any]:
    """2. agent_fill_node: LLM ReAct Agent 全自主标书撰写——
    自行阅读 Word 文档 → 理解各章节要求 → 查询数据库获取事实 → 组织语言撰写内容 → OfficeCLI 写入 Word"""
    logger.info("📍 [LangGraph Node 2/3] agent_fill_node: 启动全自主标书撰写 Agent...")
    doc_id = state.get("document_id", "")
    original_context = state.get("original_context", "")
    docx_temp_path = state.get("docx_temp_path")
    slot_analysis = state.get("slot_analysis")  # LLM Slot Analyzer 预识别结果
    audit_items: List[FillingAuditItem] = []

    if not hasattr(llm_service, 'raw_llm') or llm_service.raw_llm is None:
        logger.error("LLM 服务尚未初始化，无法启动标书撰写 Agent")
        return {"audit_items": audit_items}

    # ================================================================
    # 构造 Agent 工具箱：直接复用 bid_db_tools.py 的 6 个 @tool + 3 个 OfficeCLI MCP 工具
    # ================================================================
    try:
        from app.agents.tools.bid_db_tools import get_all_bid_db_tools
        db_tools = get_all_bid_db_tools()
        logger.info(f"   ✅ 成功加载 {len(db_tools)} 个数据库直查工具（直接复用 bid_db_tools）")
    except Exception as tool_exc:
        logger.exception(f"加载数据库工具失败: {tool_exc}")
        return {"audit_items": audit_items}

    # OfficeCLI MCP 工具（自动注入临时文件路径，同步兼容包装）
    officecli_tools = []
    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            from app.mcp.office_cli_client import office_cli_mcp_client
            import asyncio
            import concurrent.futures

            def _sync_call_async(coro):
                """安全地在同步上下文（LangGraph 节点）中调用异步协程（MCP Client）。
                兼容两种情况：无事件循环 → asyncio.run()；有事件循环 → 新线程中运行。"""
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return asyncio.run(coro)
                # 有运行中的事件循环（FastAPI 请求上下文），在新线程独立事件循环中执行
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()

            @tool
            def officecli_query_doc_structure(selector: str = "paragraph") -> str:
                """查询当前投标文件 Word 文档的 DOM 结构（段落、表格、单元格）。
                ⚠️ 撰写前必须先调用此工具了解文档的完整结构——有哪些章节、段落、表格、占位符。
                参数 selector: 'paragraph'（段落）、'table'（表格）、'all'（全部）。"""
                logger.info(f"   🤖 Agent 调用 officecli_query_doc_structure(selector='{selector}')")
                coro = office_cli_mcp_client.query_structure(docx_temp_path, selector)
                res = _sync_call_async(coro)
                return res.get("structure", str(res)) if isinstance(res, dict) else str(res)

            @tool
            def officecli_batch_update(batch_commands_json: str) -> str:
                """对当前 Word 文档执行批量修改——替换段落文本、填充表格单元格、调整格式。
                参数 batch_commands_json: JSON 字符串，格式为命令列表。
                每条命令: {"command":"set","path":"/body/p[1]/r[2]","props":{"text":"新文本","underline":"single"}}"""
                logger.info("   🤖 Agent 调用 officecli_batch_update 修改 Word")
                coro = office_cli_mcp_client.batch_update(docx_temp_path, batch_commands_json)
                res = _sync_call_async(coro)
                return str(res)

            @tool
            def officecli_add_table_row(table_path: str, row_values_json: str) -> str:
                """向当前 Word 文档的指定表格追加一行数据。
                参数 table_path: 表格路径，如 '/body/tbl[1]'；
                参数 row_values_json: JSON 数组字符串，如 '["值1","值2","值3"]'。"""
                logger.info(f"   🤖 Agent 调用 officecli_add_table_row(path='{table_path}')")
                coro = office_cli_mcp_client.add_table_row(docx_temp_path, table_path, row_values_json)
                res = _sync_call_async(coro)
                return str(res)

            officecli_tools = [officecli_query_doc_structure, officecli_batch_update, officecli_add_table_row]
            logger.info(f"   ✅ 成功加载 3 个 OfficeCLI MCP Word 修改工具（文件: {docx_temp_path})")

            # 表格智能分析工具（集成 TableAgent 的零硬编码表格列语义映射能力）
            @tool
            def analyze_word_table(table_path: str, section_context: str = "") -> str:
                """【表格结构分析工具】分析 Word 文档中指定表格的业务类型与列语义映射。
                当遇到表格（如报价清单、资质证书表、人员配备表、偏离响应表）且不确定如何填充时，调用此工具获取列映射。
                参数 table_path: 表格路径（如 '/body/tbl[1]'）；
                参数 section_context: 表格所在的章节标题（如 '五、投标配置及分项报价表'），可选。"""
                import json
                # 从 OfficeCLI 查询到的表格中提取表头列名
                try:
                    from app.agents.nodes.table_agent import analyze_table_structure_and_map
                    # 构造表头文本：从 section_context 推断章节名，传入 TableAgent 分析
                    decision = analyze_table_structure_and_map(
                        header_texts=[],
                        current_section=section_context or table_path,
                    )
                    result = {
                        "table_type": decision.table_type,
                        "reason": decision.table_reason,
                        "column_mappings": [
                            {"col_index": cm.col_index, "header_name": cm.header_name,
                             "field_key": cm.field_key, "default_val": cm.default_val}
                            for cm in decision.column_mappings
                        ],
                        "hint": "请依据 table_type 选择对应的数据来源（pricing_bom→查成本数据, qualification_certs→查资质DB, team_personnel→查人员元数据, clause_compliance→查评标要求）"
                    }
                    logger.info(f"   🤖 Agent 调用 analyze_word_table(path='{table_path}', section='{section_context}') → {decision.table_type}")
                    return json.dumps(result, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.error(f"表格分析工具异常: {e}")
                    return f"表格分析失败: {str(e)}"

            officecli_tools.append(analyze_word_table)
            logger.info("   ✅ 已附加 TableAgent 表格智能分析工具")
        except ImportError as exc_import:
            logger.warning(f"   ⚠️ OfficeCLI MCP 工具加载失败（仅限 DB 查询模式）: {exc_import}")
    else:
        logger.warning("   ⚠️ docx_temp_path 为空，OfficeCLI MCP 工具不可用")

    # 组装完整工具集（6 DB 直查 + 3 OfficeCLI MCP + 1 TableAgent）
    agent_tools = db_tools + officecli_tools
    agent = create_react_agent(llm_service.raw_llm, agent_tools)

    # --- 轻量文件快照沙箱：Agent 动手前备份 ---
    sandbox_backup_path = None
    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            sandbox_backup_path = docx_temp_path + ".sandbox_backup"
            shutil.copy2(docx_temp_path, sandbox_backup_path)
            logger.info(f"   📦 [Sandbox] 已创建 Word 文件快照备份")
        except Exception as snap_exc:
            logger.warning(f"   ⚠️ [Sandbox] 备份快照失败: {snap_exc}")

    # ================================================================
    # 构建 CO-STAR 框架 Prompt：Agent 是标书撰写专家
    # ================================================================
    officecli_note = ""
    if officecli_tools:
        officecli_note = f"""当前 Word 文件路径: {docx_temp_path}
你可以使用 OfficeCLI 工具直接读取和修改这份 Word 文件。"""

    # System Prompt（静态部分 — 利用 LLM prompt caching 减少 Token 消耗）
    system_prompt = """你是一位顶级的招投标文书编制专家，拥有 15 年标书撰写经验。
你面对的是一份从招标文件中提取的《投标文件格式》Word 模板，你需要自主完成整份投标文件的撰写。

【核心工作流 — 必须严格遵循】
1. 📖 阅读理解：用 officecli_query_doc_structure 完整阅读 Word 文档 DOM 结构，理解每个章节的业务语境、每个空白处的填写意图
2. 🔍 精准查库：根据每个空白的业务意图，选择最匹配的数据库工具查询真实数据
3. 🧠 专家撰写（最关键！）：拿到数据库原始数据后，你绝不能直接粘贴！必须作为标书专家思考：
   - 这个空白在什么章节？是什么语境？（投标函 → 正式法律文书语气 / 开标一览表 → 精确数字 / 承诺书 → 规范声明）
   - 数据应该如何措辞、格式化、加上恰当的标书惯用语？
   - 下文会详细列出各种场景的处理规则
4. ✍️ 原位写盘：用 officecli_batch_update 将撰写好的内容精准写入 Word

【Objective - 核心目标】
这份 Word 模板是甲方要求的投标文件格式，包含各个章节（投标函、法定代表人授权书、
开标一览表、报价表、资格证明等），每个章节中有需要你填写的空白处、下划线占位符、空白表格等。

🚨 最高指令：你是一位标书撰写专家，不是数据搬运工！
数据库返回的原始数据只是"素材"，你必须对每个字段进行专业的标书语言转化后才能写入 Word。
绝对禁止将数据库返回值原封不动地填入任何位置！

【🧠 标书专家撰写规则 — 各场景处理范例】

■ 公司名称类字段：
  ❌ 错误：数据库返回 "XXX建设工程有限公司" → 直接填入 "XXX建设工程有限公司"
  ✅ 正确：根据所在章节判断 —
    - 投标函落款处 → "投标人：XXX建设工程有限公司（盖章）"
    - 封面处 → 直接填公司全称即可
    - 法定代表人授权书 → "XXX建设工程有限公司（投标人名称）"

■ 人员姓名字段：
  ❌ 错误：数据库返回 "XXX（法定代表人姓名）" → 直接填 "XXX"
  ✅ 正确：根据语境 —
    - "法定代表人：___" → "法定代表人：XXX（法定代表人姓名）"
    - "授权下述签字人___" → "授权下述签字人：XXX（授权代表姓名及职务）"

■ 金额数字字段：
  ❌ 错误：数据库返回 "XXXXXX.XX" → 直接填 "XXXXXX.XX"
  ✅ 正确：根据位置判断格式 —
    - 大写栏（"投标总报价（大写）"）→ "人民币 XXXX元整"
      提示：调用 query_financial_quotation_tool 的 total_price_chinese 获取标准汉字大写！
    - 小写栏 → "¥XXX,XXX.XX 元"（带千分位逗号 + 货币符号 + 单位）
    - 表格数字列 → "XXX,XXX.XX"（仅千分位数字）

■ 日期字段：
  ❌ 错误：填 "YYYY-MM-DD" 或 "YYYY/MM/DD"
  ✅ 正确：填 "XXXX 年 XX 月 XX 日"（中文日期格式，数字间加空格，用中文年月日）

■ 工期/交货期字段：
  ❌ 错误：数据库返回 "XX"（仅为数字） → 直接填 "XX"
  ✅ 正确："XX 日历天" 或 "按招标文件要求执行（XX 日历天）"

■ 质量标准字段：
  ❌ 错误：数据库返回 "合格" → 直接填 "合格"
  ✅ 正确："合格，达到国家及行业现行规范标准"（扩展为完整的标书规范措辞）

■ 地址/联系方式字段：
  ❌ 错误：数据库返回 "XXX省XXX市XXX区XXX路XXX号" → 直接粘贴
  ✅ 正确：保留原标书引导词（如 "地  址："），仅将空白/下划线处替换为地址原文，不增删引导词

■ 保证金字段：
  ❌ 错误：数据库返回 "XXXXX.XX" → 直接填数字
  ✅ 正确："人民币XXX元整（¥XXX.XX）" 或 "按招标文件规定全额缴纳"（附大写+小写双格式）

■ 空表格单元格：
  ❌ 错误：把上一行的单元格内容复制到空行
  ✅ 正确：调用对应 DB 工具获取完整数据清单，逐行填充，表头行绝不修改，数值列右对齐思维

【Steps - 推荐操作流程】
1. officecli_query_doc_structure → 全面了解文档结构、各章节语境
2. 识别每个空白/下划线/占位符的业务意图（这是什么字段？在什么章节？期望什么格式？）
3. 分类决定查询哪个 DB 工具获取原始数据
4. 🧠 用上述"标书专家撰写规则"对每个数据做专业转化和措辞
5. officecli_batch_update → 将撰写好的内容写入 Word
6. 如有空白表格需要填充数据行 → officecli_add_table_row
7. 遇到复杂表格不确定列语义 → analyze_word_table

【Safety - 强约束与防幻觉规则】
- 🚫 严禁照搬数据库原始值！每个字段都必须经过标书语言转化！
- 🚫 严禁编造任何数据！所有事实数据必须来自数据库查询结果；
- 若数据库中确实没有对应数据，标注 '[待补充: 原因]' 而非猜测值或虚构值；
- 大写金额必须使用 query_financial_quotation_tool 的 total_price_chinese 返回的标准汉字大写；
- ⚠️ 调用 query_project_metadata_tool、query_financial_quotation_tool、query_evaluation_method_tool 时，必须传入 document_id 参数；
- 🚫 不要修改模板原有的任何文字——只能填写空白处、下划线处、空白表格单元格；
- 如果模板某个章节完全不需要填写（纯说明文字），不要改动它。
- 填写完成后，再次通读该段落，确认语句通顺、格式规范、符合招投标文书惯例。

【⚠️ OfficeCLI 路径构造规则 — 必须严格遵循】
构造 officecli_batch_update 的 path 参数时，必须使用 officecli_query_doc_structure 返回的精确路径：
1. 段落路径格式：`/body/p[N]/r[M]`，其中 N 和 M 必须是正整数索引（如 p[1]、r[1]），绝对禁止使用 p[@paraId=XXX] 这种属性选择器！
2. 表格单元格路径格式：`/body/tbl[N]/tr[M]/tc[K]/p[1]`，N/M/K 必须为正整数索引
3. 写入表格空单元格时，如果单元格没有 r（run）节点，改用 officecli_add_table_row 追加完整行，或者先用 path `/body/tbl[N]/tr[M]/tc[K]/p[1]`（不指定 r）
4. 永远使用 officecli_query_doc_structure 返回的实际路径，不要自行拼装路径！

【Output - 写盘后的最终汇报】
完成所有 Word 写入后，请用一段话总结你做了哪些撰写工作：
- 填写了哪些关键字段，每个字段是如何从原始数据转化为标书用语的
- 哪些位置因数据缺失标注了待补充
- 总共修改了多少处"""

    # User Prompt（动态部分 — 每次调用的文档特定信息）
    user_prompt = f"""【Context - 任务上下文】
- 文档 ID: {doc_id}
{officecli_note}
- 以下是从 Word 模板中提取的全文上下文（供你快速了解文档整体结构，详细结构请通过 OfficeCLI 工具自行查看）：
\"\"\"
{original_context[:15000]}
\"\"\"

{_build_slot_hint(slot_analysis)}

请开始你的 ReAct 思考与工具调用循环，完成整份投标文件的撰写。"""

    from langchain_core.messages import SystemMessage, HumanMessage

    # ================================================================
    # 执行 Agent 自主思考循环（带超时保护与重试机制）
    # ================================================================
    MAX_RETRIES = int(os.getenv("BID_FILLER_MAX_RETRIES", "2"))
    AGENT_TIMEOUT_SEC = int(os.getenv("BID_FILLER_AGENT_TIMEOUT_SEC", "600"))
    last_error: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"   🤖 启动全自主标书撰写 Agent（{len(agent_tools)} 个工具, 第 {attempt}/{MAX_RETRIES} 次尝试, 超时 {AGENT_TIMEOUT_SEC}s）...")

            result = agent.invoke(
                {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]},
                config={"recursion_limit": 50}
            )
            final_msg = result["messages"][-1].content
            logger.info(f"   🤖 Agent 完成撰写，最终回复长度: {len(final_msg)} 字符")

            # Agent 成功 → 保留 OfficeCLI 修改，删除快照备份
            if sandbox_backup_path and os.path.exists(sandbox_backup_path):
                try:
                    os.remove(sandbox_backup_path)
                    logger.info("   📦 [Sandbox] Agent 撰写成功，已清理快照备份")
                except Exception:
                    pass

            audit_items.append(FillingAuditItem(
                target_field="[Agent 全自主撰写]",
                raw_requirement=f"LLM ReAct Agent 自主阅读 Word → 查询数据库 → 组织语言 → OfficeCLI 写盘 (尝试 {attempt}/{MAX_RETRIES})",
                format_style="Agent 自主撰写",
                tool_called="create_react_agent + bid_db_tools + officecli_mcp",
                data_source_table="llm_react_agent",
                db_raw_value=final_msg[:500],
                final_filled_value=f"Agent 使用 {len(agent_tools)} 个工具自主完成标书撰写",
                alignment_status="✅ LLM ReAct Agent 全自主标书撰写闭环",
                has_underline=False,
                source_type="agent_autonomous",
                confidence=0.90,
                agent_reasoning=final_msg[:500]
            ))
            last_error = None  # 成功后清除错误标记
            break  # 成功则退出重试循环

        except Exception as agent_exc:
            last_error = str(agent_exc)
            logger.warning(f"   ⚠️ Agent 执行第 {attempt}/{MAX_RETRIES} 次尝试失败: {agent_exc}")
            # 恢复 Word 文件快照
            if sandbox_backup_path and os.path.exists(sandbox_backup_path) and docx_temp_path:
                try:
                    shutil.copy2(sandbox_backup_path, docx_temp_path)
                    logger.info(f"   📦 [Sandbox] 第 {attempt} 次尝试失败，Word 文件已从快照恢复")
                except Exception as restore_exc:
                    logger.error(f"   ❌ [Sandbox] 快照恢复失败: {restore_exc}")

            if attempt < MAX_RETRIES:
                logger.info(f"   🔄 将在短暂延迟后重试 Agent（剩余 {MAX_RETRIES - attempt} 次）...")
                import time as _time
                _time.sleep(2)  # 短暂冷却，避免瞬时重试
            else:
                logger.error(f"   ❌ Agent 已达最大重试次数 ({MAX_RETRIES})，放弃重试")

    # 所有重试均失败
    if last_error:
        if sandbox_backup_path and os.path.exists(sandbox_backup_path):
            try:
                os.remove(sandbox_backup_path)
            except Exception:
                pass
        emit_error_msg = last_error[:200]
        logger.error(f"❌ 全自主标书撰写 Agent 最终失败: {emit_error_msg}")
        audit_items.append(FillingAuditItem(
            target_field="[Agent 执行失败]",
            raw_requirement=f"Agent 在 {MAX_RETRIES} 次重试后全部失败",
            format_style="N/A",
            tool_called="create_react_agent (failed)",
            data_source_table="N/A",
            db_raw_value="",
            final_filled_value=f"Agent 执行异常: {emit_error_msg}",
            alignment_status="❌ Agent 执行失败",
            has_underline=False,
            source_type="agent_failure",
            confidence=0.0,
            agent_reasoning=emit_error_msg
        ))

    return {
        "audit_items": audit_items,
        "docx_temp_path": docx_temp_path,  # 透传临时文件路径
    }


def write_docx_node(state: BidFillerState) -> Dict[str, Any]:
    """3. write_docx_node: 从临时文件读取 Agent 修改后的 Word 并输出最终字节流"""
    logger.info("📍 [LangGraph Node 3/3] write_docx_node: 从临时文件读回 Agent 修改后的 Word...")
    doc_id = state.get("document_id", "")
    docx_temp_path = state.get("docx_temp_path")
    audit_items = state.get("audit_items", [])

    filled_bytes: Optional[bytes] = None
    used_temp_file = False

    # 优先从临时文件读取（含 Agent OfficeCLI 修改）
    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            with open(docx_temp_path, "rb") as f_temp:
                filled_bytes = f_temp.read()
            used_temp_file = True
            logger.info(f"   📄 从临时文件读取 Word（含 Agent 撰写内容）: {len(filled_bytes)} bytes")
        except Exception as exc_read:
            logger.warning(f"   ⚠️ 读取临时文件失败: {exc_read}")
    if not filled_bytes:
        filled_bytes = state.get("original_docx")
        logger.info("   📄 回退使用原始字节流")

    # 清理临时文件
    if docx_temp_path and os.path.exists(docx_temp_path):
        try:
            os.remove(docx_temp_path)
            logger.info(f"   🧹 已清理临时文件: {docx_temp_path}")
        except Exception:
            pass

    source_label = "Agent 已撰写的临时文件" if used_temp_file else "原始字节流"
    report = BidFillAuditReport(
        document_id=doc_id,
        total_fields_count=len(audit_items),
        audit_items=audit_items,
        summary_note=f"BidFillerAgent 全自主标书撰写完成（数据源: {source_label}）"
    )

    return {
        "filled_docx_bytes": filled_bytes,
        "audit_report": report,
    }

def _clean_and_parse_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """容错解析大模型返回的 JSON，自动剥离 codeblock 并转义字符串内部的未转义换行符"""
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
            string_content = m.group(1)
            escaped_content = string_content.replace('\n', '\\n').replace('\r', '\\r')
            return f'"{escaped_content}"'

        fixed_json = re.sub(r'"((?:[^"\\]|\\.)*)"', replace_newlines_in_strings, cleaned, flags=re.DOTALL)
        return json.loads(fixed_json, strict=False)
    except Exception as e:
        logger.warning(f"脏 JSON 尝试修补解析失败: {e}")
        return None




def build_bid_filler_graph():
    """构建 LangGraph 全自主标书撰写状态图（3 节点线性流转）"""
    workflow = StateGraph(BidFillerState)

    workflow.add_node("scan_node", scan_node)
    workflow.add_node("agent_fill_node", agent_fill_node)
    workflow.add_node("write_docx_node", write_docx_node)

    workflow.set_entry_point("scan_node")
    workflow.add_edge("scan_node", "agent_fill_node")
    workflow.add_edge("agent_fill_node", "write_docx_node")
    workflow.add_edge("write_docx_node", END)

    return workflow.compile()


bid_filler_graph_app = build_bid_filler_graph()


class BidFillerAgent:
    """包装类：保持与原有 API 的全兼容接口"""

    def process_filling_tasks(
        self,
        db: Session,
        document_id: str,
        profile: CompanyProfile,
        detected_placeholders: List[Dict[str, Any]],
        original_docx: Optional[bytes] = None,
    ) -> tuple[Dict[str, str], BidFillAuditReport, Optional[bytes]]:
        """
        通过调用编译好的 LangGraph 全自主标书撰写状态图执行任务。

        参数:
          - detected_placeholders: 保留参数以兼容旧调用方，Agent 不再依赖此数据，
            而是自行通过 OfficeCLI 阅读 Word 文档来发现需要填写的所有位置。
        返回:
          (replacement_map, audit_report, filled_docx_bytes)
        """
        logger.info(f"🚀 启动 LangGraph BidFillerAgent 全自主标书撰写状态图...")

        initial_state: BidFillerState = {
            "document_id": document_id,
            "original_context": "",
            "db_session": db,
            "company_profile": profile,
            "original_docx": original_docx,
            "docx_temp_path": None,
            "audit_items": [],
            "audit_report": None,
            "filled_docx_bytes": None,
        }

        final_state = bid_filler_graph_app.invoke(initial_state)

        audit_report = final_state.get("audit_report") or BidFillAuditReport(
            document_id=document_id,
            total_fields_count=0,
            audit_items=[],
            summary_note="BidFillerAgent 全自主标书撰写完成"
        )
        filled_docx_bytes = final_state.get("filled_docx_bytes")

        # 返回空的 replacement_map（Agent 通过 OfficeCLI 直接写盘，不再需要外部映射）
        return {}, audit_report, filled_docx_bytes


bid_filler_agent = BidFillerAgent()


def bid_filler_orchestrator_node(state: dict) -> dict:
    """
    Orchestrator 适配节点：将方案 C (BidFillerAgent) 对接至 LangGraph 编排器。
    符合 (BiddingState) -> dict 签名，替换原 writer_agent_node。

    流程：
    1. 从 state 提取 document_id 和 tenant_id；
    2. 获取《投标文件格式》模板字节流；
    3. 委托 BidFillerAgent 执行全自主标书撰写；
    4. 将生成的 Word 落盘并更新数据库；
    5. 返回 Orchestrator 兼容的 BiddingState 更新字典。
    """
    from app.worker.tasks import emit_agent_log

    document_id = state.get("document_id")
    tenant_id = state.get("tenant_id") or "default-tenant"

    emit_agent_log(
        log_type="info",
        content="启动 BidFillerAgent (LangGraph + ReAct) 全自主标书撰写...",
        extra={"type": "worker_start", "worker": "writer_agent"}
    )

    if not document_id:
        logger.error("State 中缺少 document_id，无法启动 BidFillerAgent")
        return {"status": "writer_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        # 1. 获取《投标文件格式》模板字节流
        from app.services.bid_format_extractor_service import bid_format_extractor_service
        template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db,
            doc_id=document_id,
            tenant_id=tenant_id
        )
        if not template_bytes:
            raise ValueError("未提取到《投标文件格式》模板")

        # 2. 执行全自主标书撰写（Agent 自主发现槽位）
        _, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
            db=db,
            document_id=document_id,
            profile=CompanyProfile(),
            detected_placeholders=[],  # Agent 自主发现，不依赖预扫描
            original_docx=template_bytes,
        )

        # 3. 落盘草稿文件
        import os as _os
        base_dir = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
        drafts_dir = _os.path.join(base_dir, "uploads", "drafts")
        _os.makedirs(drafts_dir, exist_ok=True)

        draft_filename = f"draft_{document_id}.docx"
        draft_path = _os.path.join(drafts_dir, draft_filename)

        if filled_bytes:
            with open(draft_path, "wb") as f:
                f.write(filled_bytes)

        # 4. 更新数据库
        from app.db.models.project import Document as DocumentModel
        doc_obj = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if doc_obj:
            curr_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
            curr_meta["draft_path"] = draft_path
            curr_meta["draft_filename"] = draft_filename
            doc_obj.parsed_metadata = curr_meta
            db.commit()

        summary = "已成功由 BidFillerAgent 完成投标书 Word 草稿生成"
        emit_agent_log(
            log_type="info",
            content=summary,
            extra={
                "type": "worker_complete",
                "worker": "writer_agent",
                "status": "success",
                "summary": summary
            }
        )

        return {
            "completed_steps": ["writer_agent"],
            "draft_path": draft_path,
            "worker_summaries": [{
                "worker": "writer_agent",
                "status": "success",
                "summary": summary
            }]
        }

    except Exception as e:
        logger.exception(f"BidFillerAgent Orchestrator 适配节点执行失败: {e}")
        emit_agent_log("error", f"BidFillerAgent 执行失败: {str(e)}")
        return {"status": "writer_failed", "error": str(e)}
    finally:
        db.close()
