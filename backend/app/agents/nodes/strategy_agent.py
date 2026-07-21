from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
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
    hard_quals_str = "无明确提取的硬性资质"
    try:
        all_meta = document_crud.get_all_metadata(db, document_id)
        qual_md = all_meta.get("qualification")
        
        if qual_md:
            quals = []
            if qual_md.mandatory_qualifications:
                quals.append(f"- 强制性企业资质门槛: {qual_md.mandatory_qualifications}")
            if qual_md.system_certifications:
                quals.append(f"- 体系认证/特种许可: {qual_md.system_certifications}")
            if qual_md.personnel_requirements:
                quals.append(f"- 核心人员要求: {qual_md.personnel_requirements}")
            if qual_md.performance_requirements:
                quals.append(f"- 历史业绩门槛: {qual_md.performance_requirements}")
            
            if quals:
                hard_quals_str = "\n".join(quals)
    finally:
        db.close()
        
    # [RAG 兜底] 全量章节拉取，防止 Master Agent 遗漏 (开启严格模式，关闭重写发散)
    rag_text = rag_service.search_bidding_document(
        document_id, "投标人资格要求 资质 业绩 人员", top_k=3, disable_expansion=True
    )
    
    logger.info(f"--- Strategy Agent [履约盘点] ---")
    logger.info(f"Master Agent 提取的结构化资格要求: \n{hard_quals_str}")
    logger.info(f"RAG 补充检索召回的原文章节长度: {len(rag_text)} 字符")
    
    prompt = f"""
    你是一位资深的投标经理，需要从**投标方视角**全面盘点招标文件中的所有资格、资质、业绩和人员要求。
    请结合总控智能体已经提取的结构化要求，以及检索到的原文片段，基于“我公司客观条件”进行全面、客观的能力评估。
    
    【已提取的结构化资格要求】:
    {hard_quals_str}
    
    【补充检索的原文章节 (可能包含遗漏的资格要求)】:
    {rag_text}
    
    【我公司客观条件】:
    {company_quals}
    
    【任务要求】:
    1. **全面盘点**：请结合【已提取的结构化资格要求】和【补充检索的原文章节】，提取并盘点**所有的**投标人资格要求（包括但不限于：企业基本资质、体系认证、特定行业资质证书、财务要求、历史同类业绩要求、核心人员（项目经理等）资格要求等）。
    2. **绝不遗漏**：绝对不能仅仅局限于已提取的结构化要求！如果【补充检索的原文章节】中存在任何其他的资格、资质或人员门槛，必须一并独立提取并纳入盘点。
    3. 必须基于【我公司客观条件】进行比对，不要凭空捏造我公司的能力。如果我方资料中完全没有提到某项要求，请将其判定为"做不到"或"努力可做到"，并在理由中明确指出我方资料缺失。
    
    请输出 JSON 格式，包含:
    - match_score: 整体匹配度评估分 (0-100)
    - items: 数组，包含每个要求的评估：
      - requirement: 招标要求简述（如“必须具备有效的营业执照”、“项目经理需具备一级建造师证书”、“具有类似项目业绩”等）
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
    
    db: Session = SessionLocal()
    try:
        all_meta = document_crud.get_all_metadata(db, document_id)
        eval_md = all_meta.get("evaluation")
        fin_md = all_meta.get("financial")
        eng_md = all_meta.get("engineering")
        
        penalties = fin_md.delayed_payment_penalty if fin_md else ""
        payment_terms = fin_md.payment_milestones if fin_md else []
        special_conditions = eng_md.special_working_conditions if eng_md else []
    finally:
        db.close()
    
    # [靶向探雷] 针对“单方面免责”或“废标条件”这种元数据模型没覆盖到的死角，再用一次 RAG 兜底
    risk_keywords = ["单方面免责 解除合同", "废标条件 否决投标 无效投标"]
    rag_texts = []
    for kw in risk_keywords:
        res = rag_service.search_bidding_document(document_id, kw, top_k=2, disable_expansion=True)
        if res and res != "未检索到相关内容。":
            rag_texts.append(f"--- 关于【{kw}】的检索结果 ---\n{res}")
            
    aggregated_risk_context = "\n\n".join(rag_texts)
    
    logger.info(f"--- Strategy Agent [风险提示] ---")
    logger.info(f"复用主控节点提取的结构化元数据 (罚则、付款方式、高危工况) 进行风险评估。")
    
    prompt = f"""
    请分析以下招标文件内容，提取所有可能对投标方不利的风险条款（如违约金过高、账期过长、单方面免责等）。
    输出 JSON 格式，包含一个 risks 数组，每个对象包含：
    - risk_type: 风险类型（商务/法务/财务等）
    - description: 风险通俗解释
    - exact_quote: 原文对应的条款原句（必须**一字不差**，以便前端精准高亮）
    - severity: 风险级别（"高", "中", "低"）
    
    【结构化元数据 (已由主控提取)】: 
    - 违约罚则条款: {penalties}
    - 资金支付与结算节点: {payment_terms}
    - 特殊/高危施工工况: {special_conditions}

    【定向排雷检索到的高危上下文 (RAG兜底)】: 
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
