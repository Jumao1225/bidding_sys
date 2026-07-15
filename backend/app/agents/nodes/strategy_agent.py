from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.project import DocChunk, Document
from app.services.rag_service import rag_service
from app.core.audit_decorator import audit_node
import logging

logger = logging.getLogger(__name__)

@audit_node(name="StrategyAgent-AnalyzeQualifications")
def analyze_qualifications_node(state: BiddingState) -> dict:
    """
    将招标文件文本和公司已有资质发给大模型，进行三级评估。
    返回增量状态字典，用于更新 BiddingState。
    """
    company_quals = state.get("company_quals", "")
    document_id = state.get("document_id")
    
    db: Session = SessionLocal()
    hard_quals = []
    try:
        # [DB First] 直接获取 Master Agent 提炼的硬性资质
        document = db.query(Document).filter(Document.id == document_id).first()
        if document and document.parsed_metadata:
            hard_quals = document.parsed_metadata.get("hard_qualifications", [])
    finally:
        db.close()
        
    # [RAG 兜底] 全量章节拉取，防止 Master Agent 遗漏 (开启严格模式，关闭重写发散)
    rag_text = rag_service.search_bidding_document(
        document_id, "投标人资格要求 资质 业绩 人员", top_k=3, disable_expansion=True
    )
    
    hard_quals_str = "\n".join([f"- {q}" for q in hard_quals]) if hard_quals else "无明确提取的硬性资质"
    
    logger.info(f"--- Strategy Agent [履约盘点] ---")
    logger.info(f"Master Agent 提取的硬性门槛: \n{hard_quals_str}")
    logger.info(f"RAG 补充检索召回的原文章节长度: {len(rag_text)} 字符")
    
    prompt = f"""
    你是一位资深的投标经理，需要从**投标方视角**盘点招标文件中的要求。
    请结合总控智能体提取的“核心硬性门槛”，以及检索到的原文片段，基于“我公司客观条件”进行客观的能力评估。
    
    【核心硬性门槛 (Master Agent 提取)】:
    {hard_quals_str}
    
    【补充检索的原文章节】:
    {rag_text}
    
    【我公司客观条件】:
    {company_quals}
    
    请输出 JSON 格式，包含:
    - match_score: 整体匹配度评估分 (0-100)
    - items: 数组，包含每个要求的评估：
      - requirement: 招标要求简述
      - exact_quote: 从原文中提取的**一字不差**的原句（必须完全匹配原文的子串，用于前端锚点高亮展示）
      - status: 必须是以下三种之一："可以做到", "努力可做到", "做不到"
      - reason: 评估原因或行动建议
    """
    
    res = llm_service.generate_structured_json(prompt, temperature=0.0)
    return {"qualifications_analysis": res}

@audit_node(name="StrategyAgent-IdentifyRisks")
def identify_risks_node(state: BiddingState) -> dict:
    """
    扫描文本中的法律、财务、商务风险项
    """
    document_id = state.get("document_id")
    
    # [靶向探雷] 预设高危关键字列表
    risk_keywords = [
        "违约金 罚款 赔偿金",
        "付款方式 结算 账期 预付款",
        "单方面免责 解除合同",
        "废标条件 否决投标 无效投标"
    ]
    
    rag_texts = []
    for kw in risk_keywords:
        # top_k=2 因为我们启用了整章召回，拉出的文本会非常大 (开启严格模式，关闭重写发散)
        res = rag_service.search_bidding_document(document_id, kw, top_k=2, disable_expansion=True)
        if res and res != "未检索到相关内容。":
            rag_texts.append(f"--- 关于【{kw}】的检索结果 ---\n{res}")
            
    aggregated_risk_context = "\n\n".join(rag_texts)
    
    logger.info(f"--- Strategy Agent [风险提示] ---")
    logger.info(f"靶向探雷共聚合了 {len(rag_texts)} 个维度的风险片段，总长度: {len(aggregated_risk_context)} 字符")
    logger.debug(f"聚合的风险上下文内容预览:\n{aggregated_risk_context[:500]}...")
    
    prompt = f"""
    请分析以下招标文件内容，提取所有可能对投标方不利的风险条款（如违约金过高、账期过长、单方面免责等）。
    输出 JSON 格式，包含一个 risks 数组，每个对象包含：
    - risk_type: 风险类型（商务/法务/财务等）
    - description: 风险通俗解释
    - exact_quote: 原文对应的条款原句（必须**一字不差**，以便前端精准高亮）
    - severity: 风险级别（"高", "中", "低"）
    
    【定向排雷检索到的高危上下文】: 
    {aggregated_risk_context}
    """
    
    response = llm_service.generate_structured_json(prompt, temperature=0.0)
    
    if isinstance(response, list):
        risks = response
    elif isinstance(response, dict):
        risks = response.get("risks", [])
    else:
        risks = []
        
    return {"risks_analysis": risks}
