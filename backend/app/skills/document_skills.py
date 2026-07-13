from langchain_core.tools import tool

def get_search_tool(doc_id: str):
    """
    获取一个绑定了特定 document_id 的 RAG 搜索工具。
    返回的工具可直接注入到 LangChain / LangGraph Agent 中使用。
    """
    @tool
    def search_document_tool(query: str) -> str:
        """当需要了解项目细节、施工难点、特殊工况等隐藏信息时，调用此工具在完整标书中根据关键词搜索相关内容"""
        from app.services.rag_service import rag_service
        print(f"\n[🔍 Tool Action] 智能体发起了自主搜索，使用的搜索关键词是: '{query}'\n")
        return rag_service.search_bidding_document(doc_id, query)
        
    return search_document_tool
