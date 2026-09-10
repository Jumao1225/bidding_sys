import re
from typing import Iterable, List, Optional
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.services.llm_service import llm_service
from app.utils.section_title import (
    normalize_section_title,
    section_title_stem,
)


_TOC_MARKER_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|#{1,6}\s*)")

class RoutingDecision(BaseModel):
    is_global_search: bool = Field(
        ..., 
        description="是否需要进行全局搜索。如果查询词涵盖的范围极广（如财务、资质等散落在多个章节），或者无法确定具体章节，必须设为 True。如果查询词非常聚焦（如具体的评分标准、评标办法），设为 False。"
    )
    target_chapters: List[str] = Field(
        default_factory=list,
        description="最有可能包含答案的章节名称列表。必须是从大纲中精确提取的字符串。如果 is_global_search 为 True，此字段应返回空列表。"
    )


def _extract_toc_candidates(toc: object) -> list[str]:
    """从目录树文本中提取节点文本，只移除列表或 Markdown 结构标记。"""
    if isinstance(toc, (list, tuple)):
        raw_lines: Iterable[object] = toc
    else:
        raw_lines = str(toc or "").splitlines()

    candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in raw_lines:
        candidate = _TOC_MARKER_PATTERN.sub("", str(raw_line)).strip()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def _canonicalize_target_chapters(
    decision: RoutingDecision,
    toc: object,
) -> RoutingDecision:
    """把模型路由结果映射为目录树中的原文节点，禁止返回目录外的改写标题。"""
    if decision.is_global_search:
        return RoutingDecision(is_global_search=True, target_chapters=[])

    toc_candidates = _extract_toc_candidates(toc)
    if not toc_candidates:
        return RoutingDecision(is_global_search=True, target_chapters=[])

    exact_candidates: dict[str, str] = {}
    stem_candidates: dict[str, list[str]] = {}
    for candidate in toc_candidates:
        normalized_candidate = normalize_section_title(candidate)
        candidate_stem = section_title_stem(candidate)
        if normalized_candidate:
            exact_candidates.setdefault(normalized_candidate, candidate)
        if candidate_stem:
            stem_candidates.setdefault(candidate_stem, []).append(candidate)

    canonical_titles: list[str] = []
    seen_titles: set[str] = set()
    for raw_title in decision.target_chapters:
        matched_titles: list[str] = []
        raw_normalized = normalize_section_title(raw_title)
        raw_stem = section_title_stem(raw_title)
        if raw_normalized in exact_candidates:
            matched_titles = [exact_candidates[raw_normalized]]
        else:
            matched_titles = list(dict.fromkeys(stem_candidates.get(raw_stem, [])))

        if not matched_titles:
            logger.warning(
                "RoutingService: 丢弃目录树之外的路由章节返回值: {}",
                raw_title,
            )
            continue
        if len(matched_titles) > 1:
            logger.warning(
                "RoutingService: 路由标题对应多个目录节点，保留全部兼容节点：{}",
                raw_title,
            )
        for matched_title in matched_titles:
            if matched_title not in seen_titles:
                canonical_titles.append(matched_title)
                seen_titles.add(matched_title)

    if not canonical_titles:
        logger.warning("RoutingService: 局部路由未映射到任何目录节点，降级为全局检索。")
        return RoutingDecision(is_global_search=True, target_chapters=[])

    return RoutingDecision(is_global_search=False, target_chapters=canonical_titles)

class RoutingService:
    """
    动态意图路由引擎 (Dynamic Intent Routing Agent)
    分析用户提问或提取意图，结合标书大纲 (TOC)，动态返回最有可能包含答案的章节列表。
    """
    
    def analyze_intent_and_route(
        self,
        document_id: str,
        query: str,
        tenant_id: Optional[str] = None,
    ) -> RoutingDecision:
        """
        根据 query 和 document_id，智能判断并返回路由决策（包含是否全局搜索以及目标章节）。
        """
        db: Session = SessionLocal()
        try:
            from app.core.context import current_user_id, current_tenant_id
            user_id = current_user_id.get()
            effective_tenant_id = tenant_id or current_tenant_id.get()
            
            # 如果 Context 中有用户身份，则使用严格的租户鉴权
            if user_id and effective_tenant_id:
                document = document_crud.get_document_by_id(db, document_id, user_id, effective_tenant_id)
            else:
                # 兼容不需要权限校验的后台系统级调用
                document = document_crud.get_document_by_id_system(db, document_id)
                
            if not document:
                logger.warning(f"RoutingService: 未找到文档或无权访问 {document_id}")
                return RoutingDecision(is_global_search=True, target_chapters=[])
                
            parsed_metadata = document.parsed_metadata or {}
            toc_str = parsed_metadata.get("table_of_contents", "")
            
            if not _extract_toc_candidates(toc_str):
                logger.info(f"RoutingService: 文档 {document_id} 无有效大纲(TOC)，触发降级全量搜索。")
                return RoutingDecision(is_global_search=True, target_chapters=[])
                
            prompt = f"""
你是一位顶级的标书结构分析专家和导航员。

【标书章节大纲 (TOC)】:
{toc_str}

【当前用户的意图/查询关键词】:
"{query}"

【任务】
请分析用户的查询关键词，判断该查询属于“局部知识”还是“全局知识”。
1. 局部知识：查询词指向明确的局部章节。设定 is_global_search = False，并从目录树中选择最相关的节点。
2. 全局知识：查询词覆盖范围不明确或可能跨越多个章节。设定 is_global_search = True，并将 target_chapters 设为空列表。

【返回约束】
- target_chapters 中的每一项必须逐字复制目录树中的节点文本。
- 不得改写、翻译、缩写、删除或新增章节序号，不得添加任何前缀或后缀。
- 不得返回目录树中不存在的章节名称。
- 如果无法从目录树中确定局部节点，使用全局检索。
"""
            
            logger.info(f"RoutingService: 正在对意图 '{query}' 执行全局/局部智能路由分析...")
            decision: RoutingDecision = llm_service.generate_structured_output(
                prompt=prompt,
                schema_cls=RoutingDecision,
                temperature=0.1,
                tenant_id=effective_tenant_id,
            )
            
            canonical_decision = _canonicalize_target_chapters(decision, toc_str)
            logger.info(
                "RoutingService: 意图 '%s' 路由决策 -> 全局搜索: %s, 目录节点: %s",
                query,
                canonical_decision.is_global_search,
                canonical_decision.target_chapters,
            )

            return canonical_decision
            
        except Exception as e:
            logger.exception(f"RoutingService 发生异常，降级为全量搜索: {str(e)}")
            return RoutingDecision(is_global_search=True, target_chapters=[])
        finally:
            db.close()

routing_service = RoutingService()
