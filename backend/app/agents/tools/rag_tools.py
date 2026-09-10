from typing import Optional

from langchain_core.tools import BaseTool, tool
from loguru import logger

from app.services.rag_service import rag_service
from app.services.routing_service import routing_service


def _search_bidding_document_impl(
    document_id: str,
    query: str,
    tenant_id: Optional[str] = None,
) -> str:
    """执行通用招标文档检索，并将租户 ID 显式传递给 Routing 服务。"""
    try:
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access
        from app.core.context import current_tenant_id

        # Worker 线程可能无法继承 ContextVar，因此优先使用调用方显式绑定的租户 ID。
        effective_tenant_id = tenant_id or current_tenant_id.get()

        if not validate_document_access(document_id):
            return f"拒绝访问：您无权检索文档 {document_id} 的原文内容。"

        # 动态意图路由拦截
        emit_agent_log("info", f"ChatAgent 发起通用检索: '{query}'，正在启动 Routing 意图识别引擎进行导航...")
        logger.info(
            "通用 RAG 工具调用 Routing：document_id={}，tenant_id={}",
            document_id,
            effective_tenant_id or "global",
        )
        section_titles = routing_service.analyze_intent_and_route(
            document_id,
            query,
            tenant_id=effective_tenant_id,
        )

        if section_titles:
            emit_agent_log("info", f"Routing 引擎锁定目标章节: {section_titles}")
        else:
            emit_agent_log("info", "Routing 引擎判定该问题为全局性问题，降级为全量 RAG 搜索。")

        emit_agent_log("tool_call", "调用工具: 正在执行底层 RAG 检索...")

        # 直接调用 RAG 服务，返回最相关的拼接上下文给大模型阅读
        context = rag_service.search_bidding_document(
            document_id=document_id,
            query=query,
            section_title=section_titles,
            top_k=5,
        )

        if not context or "未检索到" in context:
            return f"未能针对关键词 '{query}' 检索到相关的原文段落，请尝试换一个说法重新搜索。"

        return f"针对 '{query}'，检索到的原文上下文如下：\n\n{context}"
    except Exception as exc:
        logger.exception(
            "通用 RAG 检索失败：document_id={}，tenant_id={}，query={}",
            document_id,
            tenant_id or "global",
            query[:100],
        )
        return f"RAG 检索过程中发生错误: {str(exc)}"


@tool
def search_bidding_document(document_id: str, query: str) -> str:
    """
    【通用招标文档检索工具 (RAG)】
    当你需要从当前的招标文档中查询任何细节信息，且其他专项提取工具无法满足你的需求时，请调用此工具。
    特别注意：当用户质疑你的回答、指出数据错误，或需要明确区分两个容易混淆的概念（如“采购预算”和“最高限价”）时，你必须使用此工具回到原文进行二次核实，决不可依赖记忆。
    它可以基于语义相似度，从庞大的标书中为你精准检索出最相关的段落原文。

    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - query: 你想要查询的问题或关键词，请尽量描述得详细具体，以便向量检索更精准
    """
    return _search_bidding_document_impl(document_id=document_id, query=query)


def create_search_bidding_document_tool(tenant_id: Optional[str]) -> BaseTool:
    """创建固定租户的 RAG 工具，避免在线程池中依赖隐式上下文。"""
    bound_tenant_id = tenant_id.strip() if tenant_id and tenant_id.strip() else None

    @tool("search_bidding_document")
    def bound_search_bidding_document(document_id: str, query: str) -> str:
        """使用当前 Worker 绑定的租户检索招标文档原文。"""
        return _search_bidding_document_impl(
            document_id=document_id,
            query=query,
            tenant_id=bound_tenant_id,
        )

    logger.debug("已创建固定租户 RAG 工具：tenant_id={}", bound_tenant_id or "context")
    return bound_search_bidding_document

@tool
def get_full_chapter_text(document_id: str, chapter_name: str) -> str:
    """
    【整章原文提取工具】
    当你需要完整阅读招标文档中某个特定章节（如"合同条款"、"项目需求"、"投标人须知"、"评标办法"）的全部段落原文，
    以便进行地毯式提炼（如编制商务条款偏离表、排查废标红线）时，调用此工具。
    与普通 RAG 检索不同，本工具不会进行 Top-K 向量截断，而是按顺序拼接返回该章节的 100% 完整上下文。

    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - chapter_name: 章节名称关键字（如 "合同条款", "项目需求", "投标人须知", "评标办法"）
    """
    try:
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access

        if not validate_document_access(document_id):
            return f"拒绝访问：您无权检索文档 {document_id} 的原文内容。"

        emit_agent_log("tool_call", f"调用工具: 正在获取章节 [{chapter_name}] 的 100% 顺序全文原文...")

        res = rag_service.get_full_chapter_text(document_id, chapter_name)
        emit_agent_log("success", f"✅ 成功获取章节 [{chapter_name}] 的全量原文。")
        return res
    except Exception as e:
        return f"获取整章原文时发生错误: {str(e)}"

RAG_TOOLS = [search_bidding_document, get_full_chapter_text]
