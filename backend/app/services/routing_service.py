import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

class RoutingDecision(BaseModel):
    is_global_search: bool = Field(
        ..., 
        description="是否需要进行全局搜索。如果查询词涵盖的范围极广（如财务、资质等散落在多个章节），或者无法确定具体章节，必须设为 True。如果查询词非常聚焦（如具体的评分标准、评标办法），设为 False。"
    )
    target_chapters: List[str] = Field(
        default_factory=list,
        description="最有可能包含答案的章节名称列表。必须是从大纲中精确提取的字符串。如果 is_global_search 为 True，此字段应返回空列表。"
    )

class RoutingService:
    """
    动态意图路由引擎 (Dynamic Intent Routing Agent)
    分析用户提问或提取意图，结合标书大纲 (TOC)，动态返回最有可能包含答案的章节列表。
    """
    
    def analyze_intent_and_route(self, document_id: str, query: str) -> RoutingDecision:
        """
        根据 query 和 document_id，智能判断并返回路由决策（包含是否全局搜索以及目标章节）。
        """
        db: Session = SessionLocal()
        try:
            document = document_crud.get_document_by_id(db, document_id)
            if not document:
                logger.warning(f"RoutingService: 未找到文档 {document_id}")
                return []
                
            parsed_metadata = document.parsed_metadata or {}
            toc_str = parsed_metadata.get("table_of_contents", "")
            
            if not toc_str or len(toc_str.strip()) < 10:
                logger.info(f"RoutingService: 文档 {document_id} 无有效大纲(TOC)，触发降级全量搜索。")
                return RoutingDecision(is_global_search=True, target_chapters=[])
                
            prompt = f"""
你是一位顶级的标书结构分析专家和导航员。

【标书章节大纲 (TOC)】:
{toc_str}

【当前用户的意图/查询关键词】:
"{query}"

【任务】
请分析用户的查询关键词，首先判断该查询是属于“局部知识”还是“全局知识”。
1. 局部知识：查询词非常集中、指向明确（例如“评标办法”、“评分权重”、“打分标准”），往往在某一个或两个特定章节中。你需要设定 is_global_search = False，并在 target_chapters 中返回这些章节的精确名称。
2. 全局知识：查询词非常分散，或者属于跨章节的宏观信息（例如“财务资金”可能横跨《投标邀请》的预算和《合同条款》的付款方式，“资质合规”可能横跨公告和须知）。此时，你必须设定 is_global_search = True，并将 target_chapters 设为空列表。

要求：
- 宁可全局搜索，绝不可为了精确而遗漏重要章节（例如第一章的公告/邀请通常包含核心门槛和财务金额）。如果不确定，请判定为全局搜索。
- 只要判断为 is_global_search = True，系统就会进行全文检索。
- 返回的章节名称（如果有）必须与大纲中的文字**完全一致**。
"""
            
            logger.info(f"RoutingService: 正在对意图 '{query}' 执行全局/局部智能路由分析...")
            decision: RoutingDecision = llm_service.generate_structured_output(
                prompt=prompt,
                schema_cls=RoutingDecision,
                temperature=0.1
            )
            
            logger.info(f"RoutingService: 意图 '{query}' 路由决策 -> 全局搜索: {decision.is_global_search}, 目标章节: {decision.target_chapters}")
            
            return decision
            
        except Exception as e:
            logger.exception(f"RoutingService 发生异常，降级为全量搜索: {str(e)}")
            return RoutingDecision(is_global_search=True, target_chapters=[])
        finally:
            db.close()

routing_service = RoutingService()
