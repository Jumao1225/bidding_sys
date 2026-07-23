import os
from loguru import logger
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.core.audit_decorator import audit_node
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.agents.nodes.writer_agent import (
    WordGenerator, BidDocOutline, MergedStyles, extract_styles_from_docx,
    clone_format_section_from_original_docx
)
from app.agents.nodes.writer_planner_node import plan_chapter_tasks_from_markdown
from app.agents.nodes.writer_executor_node import execute_all_chapter_tasks

from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata, 
    EngineeringMetadata, EvaluationMetadata
)
from app.db.models.project import Document


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
            
            # 搜寻所有匹配项，排除目录行（如带领导点或末尾为页码数字，如 '# 第六章 投标文件格式 40'）
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
                
                # 向上溯源：如果是从小节标题(如"投标函格式")倒推定位的，向上取 2000 字符定位大章起点
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
    Writer Agent 节点：
    1. 优先提取「投标文件格式」大章的完整 Markdown 文本 (兼顾 RAG 兜底)；
    2. 利用 LLM 抽取格式章节的目录大纲、排版规范以及各小节原汁原味的范本文本/样表；
    3. 读取数据库中的 5 大元数据以及前序 Agent 产出的策略、资质与成本分析；
    4. 执行三层样式合并与范本模板变量置换，调用 WordGenerator 动态生成投标书 Word 草稿；
    5. 将生成的草稿落盘并更新数据库元数据。
    """
    from app.worker.tasks import emit_agent_log

    document_id = state.get("document_id")
    tenant_id = state.get("tenant_id") or "default-tenant"
    user_id = state.get("user_id")
    company_quals = state.get("company_quals", "")

    emit_agent_log(
        log_type="info",
        content="启动投标书撰写专家，定位投标文件格式章节...",
        extra={"type": "worker_start", "worker": "writer_agent"}
    )

    db: Session = SessionLocal()
    file_path = ""
    md_file_path = ""
    metadata = {}
    
    parsed_meta = {}
    try:
        doc_obj = db.query(Document).filter(Document.id == document_id).first()
        if doc_obj:
            file_path = doc_obj.file_path or ""
            parsed_meta = doc_obj.parsed_metadata or {}
            md_file_path = parsed_meta.get("md_file_path", "")

        qual_md = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == document_id).first()
        fin_md = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == document_id).first()
        time_md = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == document_id).first()
        eng_md = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == document_id).first()
        eval_md = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == document_id).first()

        if qual_md:
            metadata["qualification"] = {k: v for k, v in qual_md.__dict__.items() if not k.startswith('_')}
        if fin_md:
            metadata["financial"] = {k: v for k, v in fin_md.__dict__.items() if not k.startswith('_')}
        if time_md:
            metadata["timeline"] = {k: v for k, v in time_md.__dict__.items() if not k.startswith('_')}
        if eng_md:
            metadata["engineering"] = {k: v for k, v in eng_md.__dict__.items() if not k.startswith('_')}
        if eval_md:
            metadata["evaluation"] = {k: v for k, v in eval_md.__dict__.items() if not k.startswith('_')}
    except Exception as e:
        logger.warning(f"WriterAgent 数据库元数据读取异常: {e}")
    finally:
        db.close()

    # 1. RAG 检索 + 全文大章定位，获取完整的【投标文件格式】文本
    fallback_rag_text = rag_service.search_bidding_document(
        document_id,
        "投标文件格式 投标文件组成 投标文件编制要求 投标文件格式要求 投标文件目录",
        top_k=6,
        disable_expansion=True
    )

    format_chapter_text = extract_format_chapter_markdown(md_file_path, fallback_rag_text)
    logger.info(f"WriterAgent 获取到格式章节文本总长度: {len(format_chapter_text)} 字符")

    emit_agent_log(
        log_type="info",
        content=f"📖 定位到【投标文件格式】完整大章 (共 {len(format_chapter_text)} 字符)，开始解析大纲...",
        extra={"type": "info"}
    )

    # 1.1 【一章节一任务】动态拆解标书格式大章为 Task 清单
    chapter_tasks = plan_chapter_tasks_from_markdown(format_chapter_text)
    logger.info(f"动态拆解标书格式大章完成，共得到 {len(chapter_tasks)} 个章节任务")

    emit_agent_log(
        log_type="info",
        content=f"🚀 已动态拆解出 {len(chapter_tasks)} 个章节模板任务，启动并发 Agent 填空撰写...",
        extra={"type": "info"}
    )

    # 1.2 组装底层提取好的分析数据
    qual_analysis = state.get("qualifications_analysis") or parsed_meta.get("qualifications_analysis", {})
    risks_analysis = state.get("risks_analysis") or parsed_meta.get("risks_analysis", [])
    cost_analysis = state.get("cost_analysis") or parsed_meta.get("cost_analysis", {})
    comp_quals = company_quals or parsed_meta.get("company_quals", "")

    analysis_data = {
        "qualifications_analysis": qual_analysis,
        "risks_analysis": risks_analysis,
        "cost_analysis": cost_analysis,
        "company_quals": comp_quals,
    }

    # 1.3 【按章节并发直接填空/撰写】执行所有章节任务
    import asyncio
    import concurrent.futures

    def _run_async_safely(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    chapter_results = _run_async_safely(
        execute_all_chapter_tasks(
            chapter_tasks, 
            metadata, 
            analysis_data, 
            document_id=document_id, 
            tenant_id=tenant_id
        )
    )


    # 2. 从格式大章提取大纲与排版规范（用于 Word 渲染）
    prompt = f"""
你是一位极具经验的招投标编制专家。
请仔细阅读以下从招标文件中提取出的【投标文件格式/组成要求】章节原文，
提取出招标文件要求的【投标文件目录结构】以及【排版规范】。

【格式章节原文参考】:
{format_chapter_text}
"""
    outline_obj: BidDocOutline = llm_service.generate_structured_output(
        prompt=prompt,
        schema_cls=BidDocOutline,
        temperature=0.0
    )

    # 3. 读取原始 .docx 样式 (若适用)
    docx_styles = {}
    if file_path and file_path.lower().endswith(".docx"):
        docx_styles = extract_styles_from_docx(file_path)

    # 4. 三层样式合并
    styles = MergedStyles(
        formatting_spec=outline_obj.formatting,
        docx_styles=docx_styles
    )

    # 5. 优先尝试直接从原始 .docx 深拷贝格式大章 (100% 还原原标书 WPS/Word 原生排版、边框与字体)
    docx_bytes = None
    if file_path and file_path.lower().endswith(".docx"):
        docx_bytes = clone_format_section_from_original_docx(
            file_path=file_path,
            metadata=metadata,
            analysis=analysis_data,
            chapter_results=chapter_results
        )

    # 兜底方案：若原文件非 .docx 或原深拷贝未搜寻到起点节点，使用 WordGenerator 动态拼装
    if not docx_bytes:
        generator = WordGenerator(styles=styles)
        docx_bytes = generator.generate_bidding_draft(
            outline=outline_obj,
            metadata=metadata,
            analysis=analysis_data,
            chapter_results=chapter_results
        )


    # 6. 文件落盘到 uploads/drafts/
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    drafts_dir = os.path.join(base_dir, "uploads", "drafts")
    os.makedirs(drafts_dir, exist_ok=True)

    draft_filename = f"draft_{document_id}.docx"
    draft_path = os.path.join(drafts_dir, draft_filename)

    with open(draft_path, "wb") as f:
        f.write(docx_bytes)

    logger.info(f"投标书草稿已写入文件: {draft_path}")

    # 7. 更新数据库 parsed_metadata["draft_path"] 与 ["bid_doc_outline"]
    db: Session = SessionLocal()
    try:
        doc_obj = db.query(Document).filter(Document.id == document_id).first()
        if doc_obj:
            curr_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
            curr_meta["draft_path"] = draft_path
            curr_meta["draft_filename"] = draft_filename
            curr_meta["bid_doc_outline"] = outline_obj.model_dump()
            doc_obj.parsed_metadata = curr_meta
            db.commit()
            logger.info("已成功将 draft_path 与 bid_doc_outline 更新至 parsed_metadata")
    except Exception as e:
        logger.warning(f"更新 parsed_metadata 失败: {e}")
        db.rollback()
    finally:
        db.close()

    summary = f"已成功按标书格式生成投标书 Word 草稿 ({len(outline_obj.outline)} 个顶级章节)"

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
