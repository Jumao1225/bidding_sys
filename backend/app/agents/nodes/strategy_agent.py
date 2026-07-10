from app.services.llm_service import llm_service
from app.agents.state import BiddingState

def analyze_qualifications_node(state: BiddingState) -> dict:
    """
    将招标文件文本和公司已有资质发给大模型，进行三级评估。
    返回增量状态字典，用于更新 BiddingState。
    """
    doc_text = state.get("doc_text", "")
    company_quals = state.get("company_quals", "")
    
    prompt = f"""
    你是一位资深的投标经理，需要从**投标方视角**盘点招标文件中的要求。
    请提取以下招标文件中的“资质与履约要求”，并基于“我公司客观条件”进行客观的能力评估。
    
    【招标文件提取文本】:
    {doc_text[:20000]}
    
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
    
    res = llm_service.generate_structured_json(prompt)
    return {"qualifications_analysis": res}

def identify_risks_node(state: BiddingState) -> dict:
    """
    扫描文本中的法律、财务、商务风险项
    """
    doc_text = state.get("doc_text", "")
    
    prompt = f"""
    请分析以下招标文件内容，提取所有可能对投标方不利的风险条款（如违约金过高、账期过长、单方面免责等）。
    输出 JSON 格式，包含一个 risks 数组，每个对象包含：
    - risk_type: 风险类型（商务/法务/财务等）
    - description: 风险通俗解释
    - exact_quote: 原文对应的条款原句（必须**一字不差**，以便前端精准高亮）
    - severity: 风险级别（"高", "中", "低"）
    
    文本: {doc_text[:20000]}
    """
    
    response = llm_service.generate_structured_json(prompt)
    
    if isinstance(response, list):
        risks = response
    elif isinstance(response, dict):
        risks = response.get("risks", [])
    else:
        risks = []
        
    return {"risks_analysis": risks}
