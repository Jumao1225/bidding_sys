"""
WriterSupervisor 专属工具集 (writer_supervisor_tools.py)

@deprecated: 自 2026-07-27 起，WriterSupervisor (方案 A) 已被 BidFillerAgent (方案 C) 替代。
本文件保留以备参考，请勿在新代码中引用。

功能：
提供给 WriterSupervisor ReAct 总控 Agent 调用的决策与派发工具：
1. analyze_bid_format_chapter: 分析格式大章原文，提取章节列表并进行四类分类判定；
2. spawn_chapter_agent: 派发一个 ChapterAgent 独立完成特定章节的处理；
3. review_and_assemble: 审阅所有已完成的章节结果，审查质量并组装生成 Word 投标书。
"""

import os
import json
import threading
from typing import Dict, Any, List, Optional, Literal
from loguru import logger
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.models.project import Document
from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata, 
    EngineeringMetadata, EvaluationMetadata
)
from app.agents.nodes.chapter_react_agent import run_chapter_agent
from app.agents.tools.chapter_agent_tools import (
    get_document_chapter_results, 
    clear_document_chapter_results
)
from app.agents.nodes.writer_agent import (
    WordGenerator, BidDocOutline, MergedStyles, extract_styles_from_docx,
    clone_format_section_from_original_docx
)


# ============================================================
# 1. 结构化分类 Schema 定义
# ============================================================

class ChapterClassification(BaseModel):
    """单个章节的分类提取与性质判定"""
    chapter_number: str = Field(..., description="章节编号 (如 '一', '（二）', '1.1')")
    chapter_title: str = Field(..., description="章节标题 (如 '一、投标函')")
    category: Literal["needs_fill", "needs_data", "needs_writing", "skip"] = Field(
        ...,
        description=(
            "分类判定:\n"
            "- needs_fill: 有 ____ 下划线/占位符的固定格式书信或声明;\n"
            "- needs_data: 有空白表格框架或需对照填报的材料/证书清单;\n"
            "- needs_writing: 甲方只给了标题与说明，无模版无表格;\n"
            "- skip: 甲方的提示说明、注意事项、装订要求、总目录。"
        )
    )
    category_reason: str = Field(..., description="判定该分类的一句话依据")
    mapping_hint: str = Field(
        ...,
        description="数据映射标签: bid_letter / authorization / qualification / pricing / technical / deviation / service / personnel / performance / financial / schedule / safety / _unknown"
    )
    template_text: Optional[str] = Field(None, description="原文中该章节原汁原味的示范模版文段 (needs_fill 必填)")
    content_hint: Optional[str] = Field(None, description="甲方对该章节的填写说明或要求")


class FormatAnalysisResult(BaseModel):
    """投标文件格式大章整体分析结果"""
    source_chapter: str = Field("投标文件格式", description="来源章节")
    total_chapters: int = Field(0, description="识别到的总章节数量")
    chapters: List[ChapterClassification] = Field(default_factory=list, description="所有提取到的章节分类列表")


# 全局保存大章分析中间结果 (按 document_id 隔离，线程安全)
_CHAPTER_ANALYSIS_CACHE: Dict[str, FormatAnalysisResult] = {}
_CHAPTER_ANALYSIS_CACHE_LOCK = threading.Lock()


# ============================================================
# 2. Supervisor 工具定义
# ============================================================

@tool
def analyze_bid_format_chapter(document_id: str, format_chapter_text: str) -> str:
    """
    【投标文件格式大章分析与四类判定工具】
    阅读招标文件中「投标文件格式」大章原文，识别所有的章节，并根据规则精确判定每个章节的类别：
    1. needs_fill: 带划线占位符的格式文书
    2. needs_data: 带空白表格或证书材料清单
    3. needs_writing: 纯长段落方案说明 (标记待补充)
    4. skip: 提示说明与注意事项

    参数:
      - document_id: 当前处理的招标文档 ID
      - format_chapter_text: 投标文件格式大章的完整 Markdown 文本
    """
    if not format_chapter_text or len(format_chapter_text.strip()) < 50:
        return "格式大章文本过短，无法解析。"

    prompt = f"""
你是一位顶级的工程招投标编制与格式分析专家。
请仔细阅读以下从招标文件中提取出的【投标文件格式】大章原文，
逐一识别其中所有要求投标方提交的章节，并根据严格的规则判定每个章节的性质类别。

【投标文件格式原文】:
{format_chapter_text}

【四类判定规则】:
1. needs_fill (模版填空类):
   - 原文中出现了 `____`、下划线、括号占位符、`XXX`；
   - 属于固定格式文书（如投标函、法定代表人授权书、廉洁承诺书）；
   - 有明确的"致：""兹授权""我方承诺"等书信/声明语句。
   
2. needs_data (数据与表格装配类):
   - 原文中给出了空白表格框架（如开标一览表、分项报价表、人员配备表、偏离表）；
   - 或者是列出了需要提供的证书材料清单（如资格审查资料要求提供营业执照、资质证书）。

3. needs_writing (方案撰写类):
   - 甲方只给了章节标题与简要说明/要求，没有提供示范模版或表格框架；
   - 如"技术方案""售后服务承诺""施工组织设计""安全生产方案"。

4. skip (说明提示类):
   - 属于甲方对投标人的注意事项、提示、说明；
   - 如"注：""（投标人应注意...）""以上材料均需加盖公章""装订顺序要求"；
   - 或者是格式大章的总目录与引言。

请输出结构化的 JSON 分类清单。对于 skip 类章节，也请记录但明确标注 category 为 "skip"。
"""

    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log("info", "🧠 WriterSupervisor: 正在分析格式大章并执行四类章节判定...")

        analysis_obj: FormatAnalysisResult = llm_service.generate_structured_output(
            prompt=prompt,
            schema_cls=FormatAnalysisResult,
            temperature=0.0
        )

        analysis_obj.total_chapters = len(analysis_obj.chapters)
        with _CHAPTER_ANALYSIS_CACHE_LOCK:
            _CHAPTER_ANALYSIS_CACHE[document_id] = analysis_obj

        summary = []
        for c in analysis_obj.chapters:
            summary.append(f"- [{c.chapter_number}] {c.chapter_title} -> 分类: {c.category} (映射: {c.mapping_hint})")

        res_str = f"分析完成！共识别 {analysis_obj.total_chapters} 个章节：\n" + "\n".join(summary)
        emit_agent_log("success", f"✅ 格式大章分析完成，共识别 {analysis_obj.total_chapters} 个章节")
        return res_str

    except Exception as e:
        logger.error(f"分析格式大章发生异常: {e}")
        return f"分析格式大章失败: {str(e)}"


@tool
def spawn_chapter_agent(
    document_id: str,
    chapter_title: str,
    chapter_number: str,
    mapping_hint: str,
    category: str,
    template_text: str = "",
    content_hint: str = ""
) -> str:
    """
    【单章节子 Agent 派发工具】
    为你决策要处理的特定章节创建并运行一个独立的 ChapterAgent。

    参数:
      - document_id: 招标文档 ID
      - chapter_title: 章节标题 (如 "一、投标函")
      - chapter_number: 章节编号 (如 "一")
      - mapping_hint: 映射标签 (如 "bid_letter", "qualification", "pricing")
      - category: 分类类别 (needs_fill, needs_data, needs_writing, skip)
      - template_text: 可选，原文中该章节的示范模版
      - content_hint: 可选，甲方的填写说明
    """
    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log("info", f"🚀 WriterSupervisor: 自主派发子 Agent 处理章节 [{chapter_title}]...")

        res = run_chapter_agent(
            document_id=document_id,
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            mapping_hint=mapping_hint,
            category=category,
            template_text=template_text,
            content_hint=content_hint
        )

        return json.dumps(res, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"派发子 Agent [{chapter_title}] 异常: {e}")
        return f"派发子 Agent 处理章节 [{chapter_title}] 失败: {str(e)}"


@tool
def spawn_batch_chapter_agents(document_id: str, chapters_data: str) -> str:
    """
    【批量并发章节子 Agent 派发工具 - 10倍并发提速】
    一次性并发派发所有选定的章节子 Agent (needs_fill 与 needs_data 类别)。
    内部通过 ThreadPoolExecutor 线程池并发调度所有 ChapterAgent 独立执行思考与数据填空。

    参数:
      - document_id: 招标文档 ID
      - chapters_data: 需派发的章节列表 JSON 字符串或 JSON 格式的章节数组，例:
        [
          { "chapter_title": "一、投标函", "chapter_number": "一", "mapping_hint": "bid_letter", "category": "needs_fill", "template_text": "致：___", "content_hint": "" },
          { "chapter_title": "三、开标一览表", "chapter_number": "三", "mapping_hint": "pricing", "category": "needs_data" }
        ]
    """
    try:
        from app.worker.tasks import emit_agent_log

        import re
        chapter_items = None

        if isinstance(chapters_data, list):
            chapter_items = chapters_data
        elif isinstance(chapters_data, str):
            cleaned = chapters_data.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            cleaned = cleaned.strip()

            if cleaned and cleaned.lower() not in ["auto", "all", "default"]:
                try:
                    chapter_items = json.loads(cleaned)
                except Exception:
                    try:
                        import ast
                        chapter_items = ast.literal_eval(cleaned)
                    except Exception:
                        logger.warning("LLM 传入的 chapters_data 解析 JSON 失败，准备从大章分析缓存降级兜底...")

        # 多级降级兜底：若解析失败、为空或传入 "auto"，自动从 analyze_bid_format_chapter 缓存中读取！
        if not chapter_items or not isinstance(chapter_items, list):
            with _CHAPTER_ANALYSIS_CACHE_LOCK:
                cached_analysis = _CHAPTER_ANALYSIS_CACHE.get(document_id)
                if cached_analysis and cached_analysis.chapters:
                    logger.info("成功从 _CHAPTER_ANALYSIS_CACHE 命中大章分析缓存，自动提炼 needs_fill 与 needs_data 章节进行并发派发！")
                    chapter_items = [
                        c.model_dump() for c in cached_analysis.chapters
                        if c.category in ["needs_fill", "needs_data"]
                    ]

        if not chapter_items or not isinstance(chapter_items, list):
            return "章节数组为空，未找到需派发的 needs_fill / needs_data 章节。"

        emit_agent_log(
            "info", 
            f"🚀 WriterSupervisor: 启动 10 倍并发流，同时派发 {len(chapter_items)} 个章节子 Agent 并发处理...",
            extra={"type": "batch_spawn_start", "count": len(chapter_items)}
        )


        import concurrent.futures

        def _worker(item: dict) -> dict:
            return run_chapter_agent(
                document_id=document_id,
                chapter_title=item.get("chapter_title", ""),
                chapter_number=item.get("chapter_number", ""),
                mapping_hint=item.get("mapping_hint", "_unknown"),
                category=item.get("category", "needs_fill"),
                template_text=item.get("template_text", ""),
                content_hint=item.get("content_hint", "")
            )

        max_workers = min(10, max(1, len(chapter_items)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_title = {
                executor.submit(_worker, item): item.get("chapter_title", "") 
                for item in chapter_items
            }
            results = []
            for future in concurrent.futures.as_completed(future_to_title):
                title = future_to_title[future]
                try:
                    res = future.result()
                    results.append(res)
                    logger.info(f"✅ [BatchWorker] 章节 [{title}] 并发处理完成")
                except Exception as e:
                    logger.error(f"❌ [BatchWorker] 章节 [{title}] 并发处理失败: {e}")
                    results.append({"chapter_title": title, "status": "failed", "error": str(e)})

        success_count = sum(1 for r in results if r.get("status") == "success")
        summary_str = f"🚀 批量并发处理完成！成功完成 {success_count}/{len(chapter_items)} 个章节。"
        emit_agent_log("success", summary_str)

        return json.dumps({
            "status": "success",
            "total_dispatched": len(chapter_items),
            "success_count": success_count,
            "results": results
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.exception(f"批量并发派发子 Agent 失败: {e}")
        return f"批量并发派发子 Agent 失败: {str(e)}"



@tool
def review_and_assemble(document_id: str) -> str:
    """
    【质量审查与 Word 组装工具】
    在所有选定的章节子 Agent 处理完成后，调用此工具审查各章节生成质量，
    并将处理结果合并组装为最终符合格式要求的投标书 Word 草稿 (.docx)。

    参数:
      - document_id: 招标文档 ID
    """
    db: Session = SessionLocal()
    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log("info", "📝 WriterSupervisor: 开始审核所有章节处理结果并组装 Word 文档...")

        doc_obj = db.query(Document).filter(Document.id == document_id).first()
        if not doc_obj:
            return f"未找到文档记录: {document_id}"

        file_path = doc_obj.file_path or ""
        parsed_meta = doc_obj.parsed_metadata or {}
        md_file_path = parsed_meta.get("md_file_path", "")

        # 1. 收集数据库中的 5 大元数据与前序策略分析
        metadata = {}
        qual_md = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == document_id).first()
        fin_md = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == document_id).first()
        time_md = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == document_id).first()
        eng_md = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == document_id).first()
        eval_md = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == document_id).first()

        if qual_md: metadata["qualification"] = {k: v for k, v in qual_md.__dict__.items() if not k.startswith('_')}
        if fin_md: metadata["financial"] = {k: v for k, v in fin_md.__dict__.items() if not k.startswith('_')}
        if time_md: metadata["timeline"] = {k: v for k, v in time_md.__dict__.items() if not k.startswith('_')}
        if eng_md: metadata["engineering"] = {k: v for k, v in eng_md.__dict__.items() if not k.startswith('_')}
        if eval_md: metadata["evaluation"] = {k: v for k, v in eval_md.__dict__.items() if not k.startswith('_')}

        analysis_data = {
            "qualifications_analysis": parsed_meta.get("qualifications_analysis", {}),
            "risks_analysis": parsed_meta.get("risks_analysis", []),
            "cost_analysis": parsed_meta.get("cost_analysis", {}),
            "company_quals": parsed_meta.get("company_quals", ""),
        }

        # 2. 收集章节子 Agent 提交的所有结果
        chapter_results = get_document_chapter_results(document_id)
        completed_count = len(chapter_results)

        logger.info(f"审查收集到 {completed_count} 个章节的处理结果")

        # 3. 提取排版大纲与样式
        format_chapter_text = ""
        if md_file_path and os.path.exists(md_file_path):
            try:
                with open(md_file_path, "r", encoding="utf-8") as f:
                    format_chapter_text = f.read()
            except Exception:
                pass

        prompt = f"请提取投标文件目录结构:\n{format_chapter_text[:20000]}"
        outline_obj: BidDocOutline = llm_service.generate_structured_output(
            prompt=prompt,
            schema_cls=BidDocOutline,
            temperature=0.0
        )

        docx_styles = extract_styles_from_docx(file_path) if file_path and file_path.lower().endswith(".docx") else {}
        styles = MergedStyles(formatting_spec=outline_obj.formatting, docx_styles=docx_styles)

        # 4. 优先深拷贝原生 .docx 格式
        docx_bytes = None
        if file_path and file_path.lower().endswith(".docx"):
            docx_bytes = clone_format_section_from_original_docx(
                file_path=file_path,
                metadata=metadata,
                analysis=analysis_data,
                chapter_results=chapter_results
            )

        # 兜底：动态拼装
        if not docx_bytes:
            generator = WordGenerator(styles=styles)
            docx_bytes = generator.generate_bidding_draft(
                outline=outline_obj,
                metadata=metadata,
                analysis=analysis_data,
                chapter_results=chapter_results
            )

        # 5. 落盘文件
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        drafts_dir = os.path.join(base_dir, "uploads", "drafts")
        os.makedirs(drafts_dir, exist_ok=True)

        draft_filename = f"draft_{document_id}.docx"
        draft_path = os.path.join(drafts_dir, draft_filename)

        with open(draft_path, "wb") as f:
            f.write(docx_bytes)

        # 6. 更新数据库 parsed_metadata
        curr_meta = dict(doc_obj.parsed_metadata) if doc_obj.parsed_metadata else {}
        curr_meta["draft_path"] = draft_path
        curr_meta["draft_filename"] = draft_filename
        curr_meta["bid_doc_outline"] = outline_obj.model_dump()
        doc_obj.parsed_metadata = curr_meta
        db.commit()

        summary_str = f"✅ 组装完成！合并了 {completed_count} 个章节内容，投标书 Word 草稿已生成: {draft_filename}"
        emit_agent_log("success", summary_str)
        return json.dumps({
            "status": "success",
            "draft_path": draft_path,
            "draft_filename": draft_filename,
            "processed_chapters": completed_count,
            "summary": summary_str
        }, ensure_ascii=False)

    except Exception as e:
        db.rollback()
        logger.exception(f"组装 Word 投标书失败: {e}")
        return f"审查与组装 Word 文档过程发生错误: {str(e)}"
    finally:
        db.close()


WRITER_SUPERVISOR_TOOLS = [
    analyze_bid_format_chapter,
    spawn_chapter_agent,
    spawn_batch_chapter_agents,
    review_and_assemble
]

