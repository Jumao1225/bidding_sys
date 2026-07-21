import json
from loguru import logger
from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.db.crud.business import business_crud
from app.core.audit_decorator import audit_node
from app.services.rag_service import rag_service

@audit_node(name="CostAgent-CalculateCost")
def cost_node(state: BiddingState) -> dict:
    """
    智能成本测算节点。
    由于没有直接提供 BOM 清单，我们可以让大模型直接从 doc_text 提取并测算，
    或者假设 state 中有一个 bom_items 和 price_book。
    为了简化，直接利用大模型做一次性评估。
    """
    document_id = state.get("document_id")
    user_id = state.get("user_id")
    tenant_id = state.get("tenant_id")
    
    db: Session = SessionLocal()
    try:
        document = document_crud.get_document_by_id(db, document_id, user_id, tenant_id)
        budget_limit = None
        if document and document.parsed_metadata:
            budget_limit = document.parsed_metadata.get("budget_limit")
            
        # 不再提取和拼接所有全文，改用 RAG 按需搜索
        
        # 动态获取当前租户的价格参考库
        price_refs = business_crud.get_all_price_references(db, tenant_id)
        price_book = {ref.item_name: ref.unit_price for ref in price_refs}
    finally:
        db.close()

    # 使用 RAG 靶向检索相关清单和报价信息
    rag_text = rag_service.search_bidding_document(
        document_id, 
        "采购清单 货物需求一览表 设备清单 BOM 报价", 
        top_k=5, 
        disable_expansion=True
    )
    
    # 如果没有配置价格库，给模型一个空库，让它自己评估或标为 0
    
    logger.info(f"开始成本核算节点，靶向检索文本长度: {len(rag_text)}。")

    prompt = f"""
    你是一位专业的成本核算专家。请从下面的招标文件中提取包含物品名称、数量的“采购清单(BOM)”，
    并将其与提供的“价格参考库(Price Book)”进行智能语义匹配。
    
    【检索到的可能包含清单的原文片段】:
    {rag_text}
    
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
