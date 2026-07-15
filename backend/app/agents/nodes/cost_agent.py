import json
from loguru import logger
from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk

def cost_node(state: BiddingState) -> dict:
    """
    智能成本测算节点。
    由于没有直接提供 BOM 清单，我们可以让大模型直接从 doc_text 提取并测算，
    或者假设 state 中有一个 bom_items 和 price_book。
    为了简化，直接利用大模型做一次性评估。
    """
    document_id = state.get("document_id")
    
    db: Session = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        budget_limit = None
        if document and document.parsed_metadata:
            budget_limit = document.parsed_metadata.get("budget_limit")
            
        chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).order_by(DocChunk.chunk_index).all()
        doc_text = "\n\n".join([chunk.content for chunk in chunks]) if chunks else ""
    finally:
        db.close()

    # 这里为了演示，硬编码一个简单的价格库。实际应从数据库查询或通过 Skill 查询。
    price_book = {
        "高性能服务器": 45000, 
        "千兆交换机": 3000
    }
    
    logger.info(f"开始成本核算节点，文本长度: {len(doc_text)}。")

    prompt = f"""
    你是一位专业的成本核算专家。请从下面的招标文件中提取包含物品名称、数量的“采购清单(BOM)”，
    并将其与提供的“价格参考库(Price Book)”进行智能语义匹配。
    
    【招标文件部分文本】:
    {doc_text[:20000]}
    
    【价格参考库】:
    {json.dumps(price_book, ensure_ascii=False)}
    
    任务要求：
    1. 提取文本中要求的采购清单。
    2. 尝试为采购清单中的每个物品在“价格参考库”中找到意思最相近的匹配项。
    3. 如果找到了匹配项，使用参考库中的价格作为单价；如果没有匹配到，单价记为 0。
    4. 计算每项的小计 (单价 * 数量)。
    
    请输出 JSON 格式，必须包含一个 `items` 数组。数组中每个对象必须包含:
    - name: 采购清单中原始的物品名称
    - qty: 采购数量
    - matched_name: 在参考库中匹配到的名称（如果没有匹配到，留空字符串 ""）
    - ref_price: 匹配到的单价（如果没有匹配到，返回 0）
    - subtotal: 小计金额 (qty * ref_price)
    - warning: 警告信息（如果没有匹配到，返回 "未找到相近的价格参考"；如果匹配到了，返回 ""）
    """
    
    logger.debug("正在调用 LLM 进行智能 BOM 提取和价格匹配...")
    response = llm_service.generate_structured_json(prompt)
    
    calculated_items = response.get("items", [])
    total_cost = 0
    
    for item in calculated_items:
        # 安全处理，防止大模型返回错误类型
        subtotal = item.get("subtotal", 0)
        if not isinstance(subtotal, (int, float)):
            try:
                subtotal = float(subtotal)
            except ValueError:
                subtotal = 0
        total_cost += subtotal

    logger.info(f"成本核算完成，总成本估算为: {total_cost}。")
    
    return {
        "cost_analysis": {
            "total_cost": total_cost,
            "budget_limit": budget_limit,
            "items": calculated_items
        }
    }
