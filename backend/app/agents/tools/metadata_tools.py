from langchain_core.tools import tool
import json
import re
from html import unescape
from typing import Any, Callable, Optional, Sequence

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app.services.rag_service import rag_service
from app.services.metadata.qualification_service import qualification_service
from app.services.metadata.financial_service import financial_service
from app.services.metadata.timeline_service import timeline_service
from app.services.metadata.engineering_service import engineering_service
from app.services.metadata.evaluation_service import evaluation_service
from app.services.routing_service import routing_service

FINANCIAL_BUDGET_KEYWORDS = (
    "采购总预算", "采购预算", "项目总预算", "项目预算", "预算金额", "资金预算",
)
FINANCIAL_LIMIT_KEYWORDS = (
    "最高投标限价", "最高限价", "招标控制价", "投标控制价", "最高报价限价",
)
FINANCIAL_FALLBACK_KEYWORDS = ("预算", "限价", "控制价")
FINANCIAL_CORE_MATCH_LIMIT = 4


def _normalize_table_cell(value: str) -> str:
    """清理表格单元格标签和空白，便于执行通用结构判断。"""
    text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _extract_table_rows(table_content: str) -> list[list[str]]:
    """从单个 HTML 或 Markdown 表格中提取逻辑行，不解释具体表头含义。"""
    html_rows = re.findall(
        r"<tr[\s\S]*?</tr>",
        table_content,
        flags=re.IGNORECASE,
    )
    if html_rows:
        return [
            [
                _normalize_table_cell(cell)
                for cell in re.findall(
                    r"<t[dh][^>]*>[\s\S]*?</t[dh]>",
                    row,
                    flags=re.IGNORECASE,
                )
            ]
            for row in html_rows
        ]

    lines = [line.strip() for line in table_content.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in [lines[0], *lines[2:]]
    ]


def _is_numeric_table_cell(value: str) -> bool:
    """判断单元格是否为独立数值，不绑定货币、计量单位或业务字段。"""
    return bool(
        re.fullmatch(
            r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?",
            value.strip(),
        )
    )


def _score_engineering_table_shape(table_content: str) -> int:
    """依据表格几何和数据分布筛选候选，不依赖固定表头或语义相似度。"""
    html_tables = re.findall(
        r"<table[\s\S]*?</table>",
        table_content,
        flags=re.IGNORECASE,
    )
    markdown_tables = re.findall(
        r"(?:(?:^|\n)\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)",
        table_content,
        flags=re.MULTILINE,
    )
    candidate_tables = html_tables or markdown_tables or [table_content]

    best_score = 0
    for table in candidate_tables:
        rows = _extract_table_rows(table)
        if len(rows) < 2:
            continue

        data_rows = rows[1:]
        column_count = max((len(row) for row in data_rows), default=0)
        if column_count < 3:
            continue

        numeric_columns: set[int] = set()
        short_text_columns: dict[int, list[str]] = {}
        has_long_text = False
        for row in data_rows:
            for column_index, cell in enumerate(row):
                if not cell:
                    continue
                if _is_numeric_table_cell(cell):
                    if column_index > 0:
                        numeric_columns.add(column_index)
                    continue
                if len(cell) > 12:
                    has_long_text = True
                elif len(cell) <= 12:
                    short_text_columns.setdefault(column_index, []).append(cell)

        has_repeated_short_values = any(
            len(values) > len(set(values))
            for values in short_text_columns.values()
        )
        if not numeric_columns or not (has_long_text or has_repeated_short_values):
            continue

        score = len(numeric_columns)
        if has_long_text:
            score += 2
        if has_repeated_short_values:
            score += 2
        best_score = max(best_score, score)

    return best_score


def _discover_table_chapter_titles(
    document_id: str,
    search_keywords: str,
    tenant_id: Optional[str],
) -> list[str]:
    """从当前文档中筛选具有工程清单形状的表格章节，不依赖固定表头或业务关键词。"""
    from app.db.models.project import DocChunk
    from app.db.session import SessionLocal

    # 保留 search_keywords 参数以兼容既有工具调用，但章节发现不再使用它做硬筛选。
    del search_keywords
    db = SessionLocal()
    try:
        query = db.query(DocChunk).filter(
            DocChunk.document_id == document_id,
            DocChunk.chunk_index > 0,
            or_(DocChunk.content_type.is_(None), DocChunk.content_type != "toc_block"),
            DocChunk.section_title.isnot(None),
        )
        if tenant_id:
            query = query.filter(DocChunk.tenant_id == tenant_id)

        table_section_scores: dict[str, int] = {}
        for chunk in query.order_by(DocChunk.chunk_index).all():
            content = str(chunk.content or "")
            has_html_table = bool(re.search(r"<table[\s\S]*?</table>", content, re.IGNORECASE))
            has_markdown_table = bool(
                re.search(r"(?:^|\n)\|[^\n]+\|\n\|[-:\s|]+\|", content)
            )
            if not has_html_table and not has_markdown_table:
                continue

            section_title = str(chunk.section_title or "").strip()
            if not section_title:
                continue
            shape_score = _score_engineering_table_shape(content)
            if shape_score <= 0:
                continue
            table_section_scores[section_title] = max(
                table_section_scores.get(section_title, 0),
                shape_score,
            )

        if not table_section_scores:
            logger.info(
                "未发现符合通用工程清单形状的结构化表格，继续使用 RAG 召回上下文：文档ID={}",
                document_id,
            )
            return []

        # 仅将通用数据形状符合候选条件的章节交给模型，陌生表头不会因词表缺失而被排除。
        selected_sections = list(table_section_scores)
        logger.info(
            "从文档表格分块发现工程清单候选章节：文档ID={}，章节={}，形状评分={}",
            document_id,
            selected_sections,
            {section: table_section_scores[section] for section in selected_sections},
        )
        return selected_sections
    except SQLAlchemyError:
        logger.exception("发现工程清单候选章节失败，继续使用 RAG 召回上下文：文档ID={}", document_id)
        return []
    finally:
        db.close()


def _load_engineering_table_context(
    document_id: str,
    section_title: Optional[str | list[str]],
    tenant_id: Optional[str],
) -> str:
    """直接读取候选工程表格分块，避免工程清单依赖向量相似度召回。"""
    from app.db.models.project import DocChunk
    from app.db.session import SessionLocal

    section_titles = (
        [section_title]
        if isinstance(section_title, str)
        else [str(item).strip() for item in (section_title or []) if str(item).strip()]
    )
    db = SessionLocal()
    try:
        query = db.query(DocChunk).filter(
            DocChunk.document_id == document_id,
            DocChunk.chunk_index > 0,
            or_(DocChunk.content_type.is_(None), DocChunk.content_type != "toc_block"),
        )
        if tenant_id:
            query = query.filter(DocChunk.tenant_id == tenant_id)
        if section_titles:
            query = query.filter(DocChunk.section_title.in_(section_titles))

        table_contexts: list[str] = []
        for chunk in query.order_by(DocChunk.chunk_index).all():
            content = str(chunk.content or "")
            if _score_engineering_table_shape(content) <= 0:
                continue
            source_section = str(chunk.section_title or "").strip() or "未标注章节"
            table_contexts.append(f"【来源章节：{source_section}】\n{content}")

        context = "\n\n".join(table_contexts)
        logger.info(
            "工程清单直接读取候选表格分块：文档ID={}，章节={}，表格块数={}，上下文字符数={}",
            document_id,
            section_titles or "全部候选章节",
            len(table_contexts),
            len(context),
        )
        return context
    except SQLAlchemyError:
        logger.exception("直接读取工程清单表格分块失败，将回退 RAG：文档ID={}", document_id)
        return ""
    finally:
        db.close()


def _select_financial_core_chunks(chunks: Sequence[Any]) -> list[Any]:
    """筛选包含预算或最高限价原文证据的分块，并补齐相邻上下文。"""
    if not chunks:
        return []

    sorted_chunks = sorted(chunks, key=lambda chunk: getattr(chunk, "chunk_index", 0))

    def find_matches(keywords: tuple[str, ...]) -> list[int]:
        """按关键词定位原文分块索引，保留文档中的自然顺序。"""
        return [
            index
            for index, chunk in enumerate(sorted_chunks)
            if any(keyword in str(getattr(chunk, "content", "")) for keyword in keywords)
        ]

    budget_matches = find_matches(FINANCIAL_BUDGET_KEYWORDS)
    limit_matches = find_matches(FINANCIAL_LIMIT_KEYWORDS)
    # 仅在未命中准确术语时采用宽泛词，避免大量普通“预算”描述挤掉核心金额证据。
    fallback_matches = find_matches(FINANCIAL_FALLBACK_KEYWORDS)
    target_matches = (budget_matches or fallback_matches)[:FINANCIAL_CORE_MATCH_LIMIT]
    target_matches += (limit_matches or fallback_matches)[:FINANCIAL_CORE_MATCH_LIMIT]

    selected_indexes: set[int] = set()
    for index in target_matches:
        selected_indexes.add(index)
        if index > 0:
            selected_indexes.add(index - 1)
        if index < len(sorted_chunks) - 1:
            selected_indexes.add(index + 1)

    return [chunk for index, chunk in enumerate(sorted_chunks) if index in selected_indexes]


def _build_financial_core_context(document_id: str, tenant_id: Optional[str]) -> str:
    """从原文分块中定向补充预算与限价证据，避免通用 RAG 召回遗漏核心金额。"""
    from app.db.models.project import DocChunk
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        query = db.query(DocChunk).filter(
            DocChunk.document_id == document_id,
            or_(DocChunk.content_type.is_(None), DocChunk.content_type != "toc_block"),
        )
        if tenant_id:
            query = query.filter(DocChunk.tenant_id == tenant_id)

        selected_chunks = _select_financial_core_chunks(query.order_by(DocChunk.chunk_index).all())
        if not selected_chunks:
            logger.info("财务定向上下文未匹配到预算或限价关键词，文档ID: {}", document_id)
            return ""

        context_blocks = []
        for chunk in selected_chunks:
            section_title = getattr(chunk, "section_title", None) or "正文"
            page_num = getattr(chunk, "page_num", None) or "未知"
            content = str(getattr(chunk, "content", "")).strip()
            if content:
                context_blocks.append(f"【预算/限价定向证据】(来源章节: {section_title}, 第 {page_num} 页)\n内容: {content}")

        logger.info("财务定向上下文补充 {} 个分块，文档ID: {}", len(context_blocks), document_id)
        return "\n\n".join(context_blocks)
    except SQLAlchemyError as exc:
        logger.exception("读取财务定向上下文失败，文档ID: {}，将继续使用通用 RAG", document_id)
        return ""
    finally:
        db.close()


def _extract_and_format(
    service,
    document_id: str,
    search_keywords: str,
    section_title: str = None,
    context_mode: str = "window",
    context_enricher: Optional[Callable[[str, Optional[str]], str]] = None,
    prefer_full_chapter: bool = False,
    bypass_routing_for_table_chapters: bool = False,
    direct_table_context: bool = False,
) -> str:
    """内部通用辅助方法：执行 RAG、补齐必要章节上下文并提取元数据。"""
    try:
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access
        from app.core.context import current_tenant_id

        tenant_id = current_tenant_id.get()
        
        if not validate_document_access(document_id):
            return f"拒绝访问：您无权提取文档 {document_id} 的信息。"

        has_explicit_section = bool(section_title)

        # 兜底补全逻辑：如果未传入限定章节，调用路由引擎进行动态意图识别
        if not section_title and not (
            prefer_full_chapter and bypass_routing_for_table_chapters
        ):
            emit_agent_log("info", "检测到未传入章节限定，正在启动 Routing 智能决策引擎...")
            decision = routing_service.analyze_intent_and_route(
                document_id,
                search_keywords,
                tenant_id=tenant_id,
            )
            if decision.is_global_search:
                emit_agent_log("info", "Routing 引擎决策为【全局搜索】，不限制特定章节。")
                section_title = None
            elif decision.target_chapters:
                section_title = decision.target_chapters
                emit_agent_log("info", f"Routing 引擎决策为【局部锁定】，目标章节: {section_title}")

        if not section_title and prefer_full_chapter and bypass_routing_for_table_chapters:
            emit_agent_log(
                "info",
                "工程清单未指定章节，跳过通用 Routing，改由结构化表格章节发现决定检索范围。",
            )

        # 工程清单属于多表格结构化数据，即使路由判定为全局搜索，也不能只把少量向量命中片段交给模型。
        # 这里从当前文档自身的表格分块发现候选章节，章节名称完全来自数据库原文。
        if prefer_full_chapter and not section_title:
            discovered_chapters = _discover_table_chapter_titles(
                document_id,
                search_keywords,
                tenant_id,
            )
            if discovered_chapters:
                section_title = discovered_chapters
                emit_agent_log(
                    "info",
                    f"工程清单路由未锁定章节，已根据文档表格结构补充候选章节: {discovered_chapters}",
                )
                
        context = ""
        should_use_direct_table_context = (
            direct_table_context
            and prefer_full_chapter
            and bypass_routing_for_table_chapters
            and not has_explicit_section
        )
        context = ""
        if should_use_direct_table_context:
            context = _load_engineering_table_context(
                document_id=document_id,
                section_title=section_title,
                tenant_id=tenant_id,
            )
            if context:
                emit_agent_log(
                    "info",
                    "工程清单已使用数据库直接读取的候选表格上下文，跳过向量相似度检索。",
                )

        if not context:
            log_msg = f"调用工具: 正在使用 '{search_keywords}' (模式: {context_mode}) 执行 RAG 检索..."
            if section_title:
                log_msg = f"调用工具: 正在限定章节 {section_title} 中使用 '{search_keywords}' (模式: {context_mode}) 执行 RAG 检索..."
            emit_agent_log("tool_call", log_msg)

            # 普通提取或直接表格读取无结果时，保留现有 RAG 作为安全兜底。
            context = rag_service.search_bidding_document(
                document_id=document_id,
                query=search_keywords,
                section_title=section_title,
                top_k=5,
                context_mode=context_mode,
                query_mode="split"
            )

        # 工程清单直接使用 RAG 的 chapter 模式结果：向量命中任意分块后，
        # 由 RAG 按数据库中的 section_title 收集该章节的全部原文分块。
        # 不能在这里再次调用基于模糊标题的整章查询，否则会把“响应表”等
        # 标题包含相同关键词的模板分块误当成目标章节，覆盖正确的向量召回结果。
        if should_use_direct_table_context and context:
            logger.info(
                "工程清单使用数据库直接表格上下文：文档ID={}，章节限定={}，上下文字符数={}。",
                document_id,
                section_title,
                len(context),
            )
        elif prefer_full_chapter and context_mode == "chapter":
            logger.info(
                "工程清单使用 RAG 章节召回结果：文档ID={}，章节限定={}，上下文字符数={}。",
                document_id,
                section_title,
                len(context or ""),
            )

        if context_enricher:
            enriched_context = context_enricher(document_id, tenant_id)
            if enriched_context:
                context = f"{enriched_context}\n\n===== 通用财务检索上下文 =====\n{context}"
        
        emit_agent_log("info", f"检索完成，开始进行大模型 {service.__class__.__name__} 结构化提取...")
        # 2. 专项领域提取与自动落盘
        metadata_obj = service.extract_metadata(context, document_id, tenant_id=tenant_id)
        
        emit_agent_log("success", f"✅ {service.__class__.__name__} 提取并落盘成功！")
        # 3. 格式化输出供大模型读取
        if hasattr(metadata_obj, "model_dump"):
            return json.dumps(metadata_obj.model_dump(), indent=2, ensure_ascii=False)
        else:
            return json.dumps(metadata_obj.dict(), indent=2, ensure_ascii=False)
            
    except Exception as e:
        emit_agent_log("error", f"❌ 执行提取时发生错误: {str(e)}")
        return f"执行提取时发生错误: {str(e)}"


def _get_full_chapter_context(document_id: str, section_title: Any) -> str:
    """逐个读取路由返回的章节名称，并合并可用的完整章节上下文。"""
    chapter_titles = section_title if isinstance(section_title, list) else [section_title]
    valid_titles = [str(title).strip() for title in chapter_titles if str(title).strip()]
    if not valid_titles:
        return ""

    context_blocks: list[str] = []
    for chapter_name in valid_titles:
        chapter_context = rag_service.get_full_chapter_text(document_id, chapter_name)
        if not chapter_context or chapter_context.startswith((
            "错误：", "未能在文档中检索到", "获取整章原文发生异常",
        )):
            logger.warning(
                "完整章节补取失败，跳过该章节：文档ID={}，章节={}，返回={}",
                document_id,
                chapter_name,
                chapter_context,
            )
            continue
        context_blocks.append(chapter_context)

    return "\n\n".join(context_blocks)

@tool
def extract_qualification_info(document_id: str, search_keywords: str = "资质要求 特定资格要求 营业执照 失信被执行 证书 执业资格 历史业绩 同类项目 废标项 否决投标", section_title: str = None) -> str:
    """
    【资格合规提取工具】
    当你需要评估投标是否满足特定行业资质、特种许可证、核心人员证书或历史业绩门槛时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带资质相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道资质要求在哪个具体章节（如"投标人须知"），请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(qualification_service, document_id, search_keywords, section_title)

@tool
def extract_financial_info(document_id: str, search_keywords: str = "最高限价 预算 投标保证金 履约保证金 付款方式 支付比例", section_title: str = None) -> str:
    """
    【财务资金提取工具】
    当你需要了解项目的最高限价(红线)、预算、各类保证金金额/比例，或多阶段付款节点时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带财务相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道财务要求在哪个具体章节，请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(
        financial_service,
        document_id,
        search_keywords,
        section_title,
        context_enricher=_build_financial_core_context,
    )

@tool
def extract_timeline_info(document_id: str, search_keywords: str = "项目编号 投标截止时间 开标时间 答疑截止 工期 交付时间 标书份数", section_title: str = None) -> str:
    """
    【商务时限提取工具】
    当你需要获取项目的唯一标识编号、时间排期（如开标时间、答疑死线）或要求的工期及标书装订份数时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带时限相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道时限要求在哪个具体章节，请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(timeline_service, document_id, search_keywords, section_title)

@tool
def extract_engineering_info(document_id: str, search_keywords: str = "主要设备 规格参数 货物需求表 技术规格书 工程量清单 采购清单 材质尺寸 参数要求 项目需求 分项清单 设备明细 特殊工况 现场施工难点 注意事项", section_title: str = None) -> str:
    """
    【技术工况提取工具】
    当你需要分析工程量清单中的核心设备数量，或排查现场施工是否具有特殊高危工况（如跨河、带电、高空）时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带工程量清单与技术规格相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道技术清单在哪个具体章节（如"项目需求"），请填入以缩小检索范围，防止幻觉
    """
    # 工程清单统一走 pgvector RAG：由向量检索从当前文档召回相关章节及其连续切片，
    # 不再直接读取 output.md，也不把整份原始文档无条件塞进大模型上下文。
    return _extract_and_format(
        engineering_service,
        document_id,
        search_keywords,
        section_title,
        context_mode="chapter",
        prefer_full_chapter=True,
        bypass_routing_for_table_chapters=True,
        direct_table_context=True,
    )

@tool
def extract_evaluation_info(document_id: str, search_keywords: str = "评标办法 评分权重 商务分 技术分 质保期 售后响应 违约金 扣罚", section_title: str = None) -> str:
    """
    【评价与罚则提取工具】
    当你需要了解评标的打分权重分布，或者需要分析硬性的售后要求和违约罚金条款时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带评标罚则相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道评标要求在哪个具体章节（如"评标办法"），请填入以缩小检索范围，防止幻觉
    """
    try:
        import json
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access
        from app.core.context import current_tenant_id
        
        if not validate_document_access(document_id):
            return f"拒绝访问：您无权提取文档 {document_id} 的评标与罚则信息。"
            
        if not section_title:
            emit_agent_log("info", "检测到未传入章节限定，正在启动 Routing 智能决策引擎进行导航...")
            # 仅针对“评标”部分进行意图识别，剥离罚则关键词，确保能够精确锁定评标章节
            decision = routing_service.analyze_intent_and_route(
                document_id,
                "评标办法 评分标准 商务分 技术分 价格分 权重",
                tenant_id=current_tenant_id.get(),
            )
            if decision.is_global_search:
                emit_agent_log("info", "Routing 引擎决策评标部分为【全局搜索】。")
                section_title = None
            elif decision.target_chapters:
                section_title = decision.target_chapters
                emit_agent_log("info", f"Routing 引擎决策评标部分锁定目标章节: {section_title}")
                
        emit_agent_log("tool_call", f"调用工具: 启动【评价与罚则】双路合并检索 (章节限定: {section_title})...")
        
        # 1. 检索评标部分 (受 section_title 限制)
        context_eval = rag_service.search_bidding_document(
            document_id=document_id,
            query="评标办法 评分权重 商务分 技术分 价格分",
            section_title=section_title,
            top_k=5,
            context_mode="window",
            query_mode="split"
        )
        
        # 2. 检索罚则部分 (不受 section_title 限制，强制全局搜索)
        context_penalty = rag_service.search_bidding_document(
            document_id=document_id,
            query="质保期 售后响应 违约金 扣罚 验收",
            section_title=None, 
            top_k=5,
            context_mode="window",
            query_mode="split"
        )
        
        combined_context = f"【评标标准相关上下文】\n{context_eval}\n\n================\n\n【合同售后及违约罚则相关上下文】\n{context_penalty}"
        
        emit_agent_log("info", "多路检索完成，开始进行大模型 EvaluationService 结构化提取...")
        metadata_obj = evaluation_service.extract_metadata(combined_context, document_id)
        
        emit_agent_log("success", "✅ EvaluationService (评标+罚则) 提取并落盘成功！")
        
        if hasattr(metadata_obj, "model_dump"):
            return json.dumps(metadata_obj.model_dump(), indent=2, ensure_ascii=False)
        else:
            return json.dumps(metadata_obj.dict(), indent=2, ensure_ascii=False)
            
    except Exception as e:
        emit_agent_log("error", f"❌ 执行评价提取时发生错误: {str(e)}")
        return f"执行提取时发生错误: {str(e)}"

# 统一暴露供 LangGraph Agent 绑定的工具集合
METADATA_TOOLS = [
    extract_qualification_info,
    extract_financial_info,
    extract_timeline_info,
    extract_engineering_info,
    extract_evaluation_info,
]
