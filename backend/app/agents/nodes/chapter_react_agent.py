"""
章节 ReAct 子 Agent 工厂模块 (chapter_react_agent.py)

@deprecated: 自 2026-07-27 起，ChapterAgent (方案 A) 已被 BidFillerAgent (方案 C) 替代。
本文件保留以备参考，请勿在新代码中引用。

功能：
每个章节子 Agent 都是一个独立的 create_react_agent 实例。
根据传入的章节元数据与分类类型，动态组装专属 Prompt 与工具列表，
执行独立的 Think -> Tool Call -> Observe 循环，完成章节填空、数据装配与内容提交。
"""

import time
import json
from typing import Dict, Any, List, Optional
from loguru import logger
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from app.services.llm_service import llm_service
from app.agents.tools.chapter_agent_tools import (
    search_chapter_requirements,
    query_metadata,
    query_company_qualifications,
    query_cost_estimation,
    query_strategy_analysis,
    write_chapter_content,
    _RUNNING_CHAPTER_RESULTS,
    _RUNNING_CHAPTER_RESULTS_LOCK,
)

# 工具注册表：按需求直查 PostgreSQL 数据库中心 (废除 RAG 检索，全量基于 DB 元数据)
TOOL_REGISTRY: Dict[str, List[Any]] = {
    "bid_letter":     [query_metadata, query_cost_estimation, write_chapter_content],
    "authorization":  [query_metadata, write_chapter_content],
    "qualification":  [query_company_qualifications, query_metadata, write_chapter_content],
    "pricing":        [query_cost_estimation, query_metadata, write_chapter_content],
    "cost":           [query_cost_estimation, query_metadata, write_chapter_content],
    "technical":      [query_metadata, write_chapter_content],
    "deviation":      [query_strategy_analysis, query_metadata, write_chapter_content],
    "risk":           [query_strategy_analysis, query_metadata, write_chapter_content],
    "service":        [query_metadata, write_chapter_content],
    "personnel":      [query_company_qualifications, query_metadata, write_chapter_content],
    "performance":    [query_company_qualifications, query_metadata, write_chapter_content],
    "financial":      [query_cost_estimation, query_metadata, write_chapter_content],
    "schedule":       [query_metadata, write_chapter_content],
    "safety":         [query_metadata, write_chapter_content],
    "_unknown":       [query_metadata, write_chapter_content],
}


def build_chapter_agent_prompt(
    chapter_title: str,
    chapter_number: str,
    mapping_hint: str,
    category: str,
    template_text: str,
    content_hint: str,
    document_id: str,
    pre_loaded_context: str = ""
) -> str:
    """
    为每个章节子 Agent 构建专属 Prompt。
    遵循 CO-STAR 框架 + 防幻觉与 Self-Correction 刹车机制。
    Supports 原文上下文预注入 (Pre-injection)，显著减少 LLM 工具轮询。
    """
    template_section = f"【甲方原文模版范本】:\n{template_text}\n" if template_text else ""
    hint_section = f"【甲方填写说明/提示】:\n{content_hint}\n" if content_hint else ""
    context_section = f"【招标文件中关于本章节的原文上下文 (预加载就绪)】:\n\"\"\"\n{pre_loaded_context}\n\"\"\"\n" if pre_loaded_context else ""

    return f"""
你是一位顶级的招投标文书编制专家，当前专门负责撰写章节：【{chapter_title}】。

【Context - 任务上下文】
- 文档 ID: {document_id}
- 章节编号: {chapter_number}
- 章节标题: {chapter_title}
- 映射标签 (mapping_hint): {mapping_hint}
- 任务类别 (category): {category}

{context_section}{template_section}{hint_section}

【Objective - 核心目标】
请根据该章节的类别与要求，结合上述已预加载的原文上下文以及你的可用工具，
完成该章节的精确内容撰写、模版下划线填空或表格数据装配，
**最后必须调用 write_chapter_content 工具提交你的最终结果**。

【分类处理指南】
1. 如果 category 为 'needs_fill' (下划线填空类):
   - 必须保持示范模版的原本书信/致辞/声明结构；
   - 调用 query_metadata 或 query_cost_estimation 工具查到真实的项目名称、招标编号、投标总价、买方单位等；
   - 将模版中的 `____` 下划线、括号占位符精准替换为真实的实际数据；
   - 清除 '[此处手动补充]' 类占位符。

2. 如果 category 为 'needs_data' (表格与材料装配类):
   - 如果是报价/开标一览表 (pricing/cost)：调用 query_cost_estimation 获取 BOM 清单与报价总额，整理为表格；
   - 如果是资质/证书资料 (qualification/personnel)：调用 query_company_qualifications 查询资质中心 DB 中的已有证书；
   - 如果是偏离/风险表 (deviation/risk)：调用 query_strategy_analysis 获取风险分析结果并装配响应表格。

【🚨 强约束与 Self-Correction 纠错规则】
1. 你已拥有上述预加载的招标原文上下文作为参考。优先从中提取参数；若发现上下文不足，可以再调用 search_chapter_requirements 工具补查；
2. 如果查询工具返回的数据不存在，可更换关键词重试 (最多重试 2 次)。若原文确实未交代，客观注明 [待补充]，严禁虚构或编造任何项目数据、证书编号或金额！
3. 撰写完成后，**你必须且只能调用 write_chapter_content 工具**，传入 document_id, chapter_title, mapping_hint, filled_content (及可选的 table_rows_json)，将结果落盘。

请开始你的 ReAct 思考与工具调用循环。
"""


def run_chapter_agent(
    document_id: str,
    chapter_title: str,
    chapter_number: str = "",
    mapping_hint: str = "_unknown",
    category: str = "needs_fill",
    template_text: str = "",
    content_hint: str = "",
    tenant_id: Optional[str] = "default-tenant"
) -> Dict[str, Any]:
    """
    独立且并发执行单个章节子 Agent。
    实例化带工具集与动态 Prompt 的 ReAct 智能体。
    支持上下文预注入 (Pre-injection)，极速 1~2 轮完成撰写。
    """
    hint = (mapping_hint or "_unknown").lower().strip()
    cat = (category or "needs_fill").lower().strip()

    logger.info(f"⚡ [ChapterAgent] 开始执行章节 [{chapter_title}] -> 分类: {cat}, 标签: {hint}")

    # 1. 针对 needs_writing 类型：直接标记占位符，不创建 LLM ReAct Agent
    if cat == "needs_writing":
        placeholder_text = f"【招标格式要求/提示】:\n{content_hint or template_text or '按招标文件要求填报'}\n\n[待人工补充：{chapter_title} 的具体方案与证明材料]"

        # 线程安全直接存入结果池
        with _RUNNING_CHAPTER_RESULTS_LOCK:
            if document_id not in _RUNNING_CHAPTER_RESULTS:
                _RUNNING_CHAPTER_RESULTS[document_id] = {}

            task_key = f"task_{hint}_{chapter_title}"
            _RUNNING_CHAPTER_RESULTS[document_id][task_key] = {
            "chapter_title": chapter_title,
            "mapping_hint": hint,
            "filled_content": placeholder_text,
            "table_rows": [],
            "status": "success"
        }
        
        logger.info(f"⏩ 章节 [{chapter_title}] 属于 needs_writing，已自动跳过 Agent 撰写并标注占位符。")
        return {
            "chapter_title": chapter_title,
            "mapping_hint": hint,
            "category": cat,
            "status": "success",
            "summary": "标记为待人工补充占位符"
        }

    # 2. 预加载原文上下文 (Context Pre-injection)，避免 Agent 多次调工具查原文
    pre_loaded_context = ""
    try:
        from app.agents.tools.writer_tools import retrieve_chapter_clause_requirements
        pre_loaded_context = retrieve_chapter_clause_requirements(
            document_id=document_id,
            chapter_title=chapter_title
        )
        if pre_loaded_context:
            logger.info(f"📖 [ChapterAgent] 成功为章节 [{chapter_title}] 预加载原文上下文 ({len(pre_loaded_context)} 字符)")
    except Exception as e:
        logger.warning(f"⚠️ [ChapterAgent] 预加载章节 [{chapter_title}] 原文上下文时发生异常: {e}")

    # 3. 从注册表中匹配该章节适用的工具集
    tools = TOOL_REGISTRY.get(hint, TOOL_REGISTRY["_unknown"])

    if not hasattr(llm_service, 'raw_llm') or llm_service.raw_llm is None:
        logger.error("LLM 服务尚未初始化，无法创建 ChapterAgent")
        return {"chapter_title": chapter_title, "status": "failed", "error": "LLM not initialized"}

    # 3. 创建 ReAct Agent (与 Master Agent 完全同构)
    agent = create_react_agent(llm_service.raw_llm, tools)

    prompt = build_chapter_agent_prompt(
        chapter_title=chapter_title,
        chapter_number=chapter_number,
        mapping_hint=hint,
        category=cat,
        template_text=template_text,
        content_hint=content_hint,
        document_id=document_id,
    )

    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log(
            "info", 
            f"⚡ [章节 Agent] 启动 [{chapter_title}] (类型: {cat}) 独立的 ReAct 思考循环...",
            extra={"type": "chapter_agent_start", "chapter": chapter_title, "category": cat}
        )
    except Exception:
        pass

    start_time = time.time()
    try:
        inputs = {"messages": [HumanMessage(content=prompt)]}
        result = agent.invoke(inputs)
        end_time = time.time()

        final_msg = result["messages"][-1].content
        tool_call_count = sum(1 for m in result["messages"] if hasattr(m, 'tool_calls') and m.tool_calls)

        logger.info(f"✅ [ChapterAgent] 章节 [{chapter_title}] 执行完成 (调用工具 {tool_call_count} 次, 耗时 {end_time - start_time:.1f}s)")
        return {
            "chapter_title": chapter_title,
            "mapping_hint": hint,
            "category": cat,
            "status": "success",
            "messages_count": len(result["messages"]),
            "tool_calls_count": tool_call_count,
            "execution_time_sec": round(end_time - start_time, 2)
        }
    except Exception as e:
        logger.exception(f"❌ [ChapterAgent] 章节 [{chapter_title}] 执行失败: {e}")
        return {
            "chapter_title": chapter_title,
            "mapping_hint": hint,
            "category": cat,
            "status": "failed",
            "error": str(e)
        }
