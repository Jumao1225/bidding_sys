"""
@deprecated: 自 2026-07-27 起，writer_agent_node 已被 BidFillerAgent (方案 C) 替代。
Graph builder 现在使用 bid_filler_orchestrator_node 作为 writer_agent 节点实现。
本文件保留以备回滚，请勿在新代码中引用。
"""
import os
from loguru import logger
from sqlalchemy.orm import Session
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

from app.agents.state import BiddingState
from app.core.audit_decorator import audit_node
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.db.session import SessionLocal
from app.db.models.project import Document
from app.agents.tools.writer_supervisor_tools import WRITER_SUPERVISOR_TOOLS
from app.agents.tools.chapter_agent_tools import clear_document_chapter_results

from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata, 
    EngineeringMetadata, EvaluationMetadata
)


def extract_format_chapter_markdown(md_file_path: str, fallback_rag_text: str) -> str:
    """
    无死角地毯式定位并提取「投标文件格式」专用大章的完整 Markdown 文本。
    支持匹配大章标题、小节标题（投标函格式、开标一览表）及上下文溯源。
    """
    if md_file_path and os.path.exists(md_file_path):
        try:
            with open(md_file_path, "r", encoding="utf-8") as f:
                full_text = f.read()

            import re
            pattern_main = re.compile(
                r'^(#+\s*|[*#]*\s*)(第[一二三四五六七八九十\d]+[章节篇部分]\s*投标文件格式|投标文件格式|投标文件组成|投标文件格式及要求).*$',
                re.MULTILINE | re.IGNORECASE
            )
            
            # 搜寻所有匹配项，排除目录行（如带领导点或末尾为页码数字）
            matches = list(pattern_main.finditer(full_text))
            valid_match = None

            for m in matches:
                line_text = m.group(0).strip()
                # 判别是否为目录条目或指引引用句
                is_toc = bool(re.search(r'(\.|\u2026|_|-){2,}\s*\d+|\b\d{1,3}$', line_text))
                is_ref = any(ref in line_text for ref in ["详见", "参见", "参照", "按第"])

                # 如果有多个匹配，且当前匹配位于文本前 15%（通常是目录页），优先寻找后续正文大章
                is_early_toc = (m.start() < len(full_text) * 0.15) if len(matches) > 1 else False

                if not is_toc and not is_ref and not is_early_toc:
                    valid_match = m
                    break

            # 若未找到合规项，取最后一个匹配项（正文大章通常靠后）
            if not valid_match and matches:
                valid_match = matches[-1]

            if not valid_match:
                pattern_sub = re.compile(
                    r'^(#+\s*|[*#]*\s*)([一二三四五六七八九十\d]+[、\.]\s*投标函格式|投标函格式|开标一览表).*$',
                    re.MULTILINE | re.IGNORECASE
                )
                sub_matches = list(pattern_sub.finditer(full_text))
                if sub_matches:
                    valid_match = sub_matches[-1]

            if valid_match:
                start_pos = valid_match.start()
                start_title = valid_match.group(0).strip()
                
                # 向上溯源：如果是从小节标题倒推定位的，向上取 2000 字符定位大章起点
                actual_start = max(0, start_pos - 2000) if ("投标函格式" in start_title or "开标一览表" in start_title) else start_pos
                
                extracted_chapter = full_text[actual_start:actual_start + 35000].strip()
                    
                if len(extracted_chapter) > 100:
                    logger.info(f"成功从全文定位提取出【投标文件格式】大章 Markdown，起点: '{start_title}'，长度: {len(extracted_chapter)} 字")
                    return extracted_chapter
        except Exception as e:
            logger.warning(f"从 output.md 提取格式大章失败: {e}")

    return fallback_rag_text


@audit_node(name="WriterAgent-GenerateDraft")
def writer_agent_node(state: BiddingState) -> dict:
    """
    Writer Agent 入口节点 (自主 ReAct 调度版)：
    1. 提取【投标文件格式】大章的完整 Markdown 文本 (带 RAG 兜底)；
    2. 初始化并启动 WriterSupervisor ReAct Agent；
    3. WriterSupervisor 自主思考并调用分析工具、派发 ChapterAgent 子 Agent、审查与组装 Word 文档；
    4. 将生成的 Word 投标书落盘，更新数据库并返回结果。
    """
    from app.worker.tasks import emit_agent_log

    document_id = state.get("document_id")
    tenant_id = state.get("tenant_id") or "default-tenant"

    emit_agent_log(
        log_type="info",
        content="启动投标书总控专家 (WriterSupervisor)，准备分析投标文件格式...",
        extra={"type": "worker_start", "worker": "writer_agent"}
    )

    # 清理该文档之前的运行态缓存
    clear_document_chapter_results(document_id)

    db: Session = SessionLocal()
    md_file_path = ""
    try:
        doc_obj = db.query(Document).filter(Document.id == document_id).first()
        if doc_obj and doc_obj.parsed_metadata:
            md_file_path = doc_obj.parsed_metadata.get("md_file_path", "")
    except Exception as e:
        logger.warning(f"读取文档信息异常: {e}")
    finally:
        db.close()

    # 1. 定位【投标文件格式】大章文本
    fallback_rag_text = rag_service.search_bidding_document(
        document_id,
        "投标文件格式 投标文件组成 投标文件编制要求 投标文件格式要求 投标文件目录",
        top_k=6,
        disable_expansion=True
    )
    format_chapter_text = extract_format_chapter_markdown(md_file_path, fallback_rag_text)
    logger.info(f"WriterAgent 获取到格式章节文本总长度: {len(format_chapter_text)} 字符")

    # 2. 构造并启动 WriterSupervisor ReAct Agent
    if not hasattr(llm_service, 'raw_llm') or llm_service.raw_llm is None:
        raise Exception("llm_service 尚未初始化支持 Tool Calling 的 raw_llm")

    supervisor_agent = create_react_agent(llm_service.raw_llm, WRITER_SUPERVISOR_TOOLS)

    prompt = f"""
你是一位顶级且极具经验的投标书编制总控专家 (WriterSupervisor)。

【任务指令】
当前处理的文档 ID 为：{document_id}
请仔细研读以下【投标文件格式】大章原文，指挥并调用专项工具完成整份投标书的自主编排与生成。

【投标文件格式原文】:
{format_chapter_text}

【标准工作流指示】:
1. 第一步：调用 `analyze_bid_format_chapter` 工具传入 document_id 与格式大章原文，对招标文件中的所有章节进行精准识别与四类分类判定 (needs_fill / needs_data / needs_writing / skip)。
2. 第二步：【强烈推荐 10倍并发提速】调用 `spawn_batch_chapter_agents` 工具 (可直接传入 chapters_data="auto" 或待派发的章节 JSON 数组)，开启多线程池并发处理所有 needs_fill 与 needs_data 章节！对于 needs_writing 类章节系统会自动跳过并标记占位符。

3. 第三步：在并发处理完成后，必须调用 `review_and_assemble` 工具对全书各章节成果进行质量审查，并触发 Word 文档拼装落盘。

【🚨 约束与刹车】
- 必须按照 步骤 1 -> 步骤 2 -> 步骤 3 顺序执行；
- 当第三步 `review_and_assemble` 返回组装成功消息后，直接回复：“投标书 Word 草稿组装完成”，结束任务；
- 不要输出冗长的 JSON 原始数据。
"""


    logger.info("WriterSupervisor Agent 开始自主思考并执行 Tool Calling 循环...")
    import time
    start_time = time.time()
    try:
        result = supervisor_agent.invoke({"messages": [HumanMessage(content=prompt)]})
        end_time = time.time()

        final_msg = result["messages"][-1].content
        logger.info(f"WriterSupervisor 最终回复: {final_msg} (耗时 {end_time - start_time:.1f}s)")
    except Exception as e:
        logger.exception(f"WriterSupervisor Agent 执行异常: {e}")
        # 如果 Supervisor ReAct 循环异常，打印错误日志
        emit_agent_log("error", f"WriterSupervisor 执行失败: {str(e)}")
        return {"status": "writer_failed", "error": str(e)}

    # 从数据库检索刚落盘的 draft_path
    draft_path = ""
    db: Session = SessionLocal()
    try:
        doc_obj = db.query(Document).filter(Document.id == document_id).first()
        if doc_obj and doc_obj.parsed_metadata:
            draft_path = doc_obj.parsed_metadata.get("draft_path", "")
    finally:
        db.close()

    summary = "已成功由 WriterSupervisor 调度完成投标书 Word 草稿生成"
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
