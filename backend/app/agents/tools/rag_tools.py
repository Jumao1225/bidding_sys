from langchain_core.tools import tool
from app.services.rag_service import rag_service

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
    try:
        # 直接调用 RAG 服务，返回最相关的拼接上下文给大模型阅读
        context = rag_service.search_bidding_document(document_id=document_id, query=query, top_k=5)
        
        if not context or "未检索到" in context:
            return f"未能针对关键词 '{query}' 检索到相关的原文段落，请尝试换一个说法重新搜索。"
            
        return f"针对 '{query}'，检索到的原文上下文如下：\n\n{context}"
        
    except Exception as e:
        return f"RAG 检索过程中发生错误: {str(e)}"
