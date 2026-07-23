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
    自动查询资质中心 DB (CompanyQualification) 中的已上传证书并进行精确匹配。
    返回增量状态字典，用于更新 BiddingState。
    """
    company_quals = state.get("company_quals", "")
    tenant_id = state.get("tenant_id") or "default-tenant"
    document_id = state.get("document_id")
    task_id = state.get("task_id")

    from app.worker.tasks import emit_agent_log
    from app.agents.tools.writer_tools import get_company_qualifications_tool

    emit_agent_log("info", "启动资质盘点专家...", extra={"type": "worker_start", "worker": "strategy_qual"})

    # 动态查询资质中心数据库中的已解析证书
    db_quals = get_company_qualifications_tool(tenant_id)
    db_quals_summary = ""
    if db_quals:
        lines = []
        for q in db_quals:
            lines.append(f"- 证书/资质名称: {q['name']} | 等级/类别: {q['level']} | 持证公司: {q['company_name']} | 有效期: {q['expiry_date']}")
        db_quals_summary = "【资质中心数据库记录 (来自于 CompanyQualification 表)】:\n" + "\n".join(lines)
    else:
        db_quals_summary = "【资质中心数据库暂无证书记录】"

    company_quals_combined = f"{company_quals}\n\n{db_quals_summary}".strip()
    
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
        document_id, "投标人资格要求 资质 业绩 人员 许可证", top_k=3, disable_expansion=True
    )
    
    logger.info(f"--- Strategy Agent [履约盘点] ---")
    logger.info(f"Master Agent 提取的结构化资格要求: \n{hard_quals_str}")
    logger.info(f"资质中心 DB 匹配到 {len(db_quals)} 项已有证书")
    
    prompt = f"""
    你是一位资深的投标经理，需要从**投标方视角**全面盘点招标文件中的所有资格、资质、业绩和人员要求。
    请结合总控智能体已经提取的结构化要求，以及检索到的原文片段，基于“我公司客观条件与资质中心数据库记录”进行全面、客观的能力评估。
    
    【已提取的结构化资格要求】:
    {hard_quals_str}
    
    【补充检索的原文章节 (可能包含遗漏的资格要求)】:
    {rag_text}
    
    【我公司客观条件与资质中心数据库记录】:
    {company_quals_combined}
    
    【任务要求与资质比对规则】:
    1. **全面盘点**：请结合【已提取的结构化资格要求】和【补充检索的原文章节】，提取并盘点**所有的**投标人资格要求（包括但不限于：企业基本资质、体系认证、特定行业资质许可证如《承装（修、试）电力设施许可证》、《安全生产许可证》、财务要求、同类业绩要求、核心人员等）。
    2. **精确资质对比（极其重要）**：必须死死盯住【资质中心数据库记录】中的所有证书清单！只要资质中心库中包含相符或覆盖的证书（例如已有《承装（修、试）电力设施许可证》、《安全生产许可证》等），请判定状态为 "可以做到"，并在 reason 中写明我公司具备的具体证书名称和等级！绝对禁止视而不见而误判为 "资质中心未查到" 或 "缺失"！
    3. 如果资质中心库与我方资料中确实完全没有提到某项要求，才将其判定为 "做不到" 或 "努力可做到"，并在理由中明确指出缺少该证书。
    
    请输出 JSON 格式，包含:
    - match_score: 整体匹配度评估分 (0-100)
    - items: 数组，包含每个要求的评估：
      - requirement: 招标要求简述（如“必须具备有效的营业执照”、“承装（修、试）电力设施许可证三级及以上”、“具有类似项目业绩”等）
      - exact_quote: 从原文中提取的**一字不差**的原句（必须完全匹配原文的子串，用于前端锚点高亮展示）
      - status: 必须是以下三种之一："可以做到", "努力可做到", "做不到"
      - reason: 评估原因或行动建议（如"我公司资质中心已具备《承装（修、试）电力设施许可证》三级，满足要求。"）
    """
    
    res = llm_service.generate_structured_json(prompt, temperature=0.0)
    
    summary = f"完成资质评估，得分 {res.get('match_score', 0)}"
    emit_agent_log("info", summary, extra={"type": "worker_complete", "worker": "strategy_qual", "status": "success", "summary": summary})
    
    return {
        "qualifications_analysis": res,
        "completed_steps": ["strategy_qual"],
        "worker_summaries": [{
            "worker": "strategy_qual",
            "status": "success",
            "summary": summary
        }]
    }

@audit_node(name="StrategyAgent-IdentifyRisks")
def identify_risks_node(state: BiddingState) -> dict:
    """
    扫描文本中的法律、财务、商务风险项
    """
    from app.worker.tasks import emit_agent_log
    document_id = state.get("document_id")
    task_id = state.get("task_id")
    emit_agent_log("info", "启动法务风控专家...", extra={"type": "worker_start", "worker": "strategy_risk"})
    
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
    
    # [靶向探雷] 针对"单方面免责"、"废标条件"、"排他性技术壁垒"等元数据模型没覆盖到的死角，定向 RAG 兜底
    # 三条搜索路径分别对应：法务风险 / 程序性废标风险 / 技术类围标壁垒
    risk_keywords = [
        "单方面免责 解除合同",
        "废标条件 否决投标 无效投标",
        "指定品牌 单一来源 特定厂商 专有技术 排他 必须兼容 原厂",  # 技术壁垒/围标暗坑
    ]
    rag_texts = []
    for kw in risk_keywords:
        res = rag_service.search_bidding_document(document_id, kw, top_k=2, disable_expansion=True)
        if res and res != "未检索到相关内容。":
            rag_texts.append(f"--- 关于【{kw}】的检索结果 ---\n{res}")
            
    aggregated_risk_context = "\n\n".join(rag_texts)
    
    logger.info(f"--- Strategy Agent [风险提示] ---")
    logger.info(f"复用主控节点提取的结构化元数据 (罚则、付款方式、高危工况) 进行风险评估。")
    
    prompt = f"""
    你是一名拥有20年经验的招投标法务风控专家。请从以下招标文件内容中，**穷尽式**提取所有对投标方不利的风险条款。
    
    【必须覆盖的四类风险】：
    1. **商务/财务风险**：违约金过高、账期过长、质保金比例异常、背靠背付款、预付款缺失等。
    2. **法务风险**：单方面免责条款、合同可被甲方单方解除的条款、歧视性或不对等条款等。
    3. **程序性废标风险**：不满足即直接导致废标的条款（如：未盖章、未提供某份证明等），注意此类风险不一定带有"废标"字样，需凭经验识别隐蔽形式。
    4. **技术壁垒/围标风险（重点关注）**：要求指定单一品牌或厂商的设备、要求必须与特定竞争对手系统兼容对接、要求原厂认证证书（实质是品牌锁定）、具有排他性的量化技术参数要求。此类风险是隐蔽的围标手段，一旦遗漏将直接失去投标资格。

    输出 JSON 格式，包含一个 risks 数组，每个对象包含：
    - risk_type: 风险类型，从【商务、法务、财务、程序性废标、技术壁垒】中选择一个
    - description: 风险通俗解释（说明为什么有风险，对我方的实际影响是什么）
    - exact_quote: 原文对应的条款原句（必须**一字不差**，以便前端精准高亮）
    - severity: 风险级别（"高", "中", "低"）
    
    【结构化元数据 (已由主控提取)】: 
    - 违约罚则条款: {penalties}
    - 资金支付与结算节点: {payment_terms}
    - 特殊/高危施工工况: {special_conditions}

    【定向排雷检索到的高危原文 (法务/废标/技术壁垒三路召回)】: 
    {aggregated_risk_context}
    
    【重要提醒】：严禁凭空捏造，所有风险项的 exact_quote 必须来自上述上下文原文。若上下文中确无相关内容，该类风险不输出，不允许虚构原文。
    """
    
    response = llm_service.generate_structured_json(prompt, temperature=0.0)
    
    if isinstance(response, list):
        risks = response
    elif isinstance(response, dict):
        risks = response.get("risks", [])
    else:
        risks = []
        
    summary = f"排查出 {len(risks)} 项风险"
    emit_agent_log("info", summary, extra={"type": "worker_complete", "worker": "strategy_risk", "status": "success", "summary": summary})
    
    return {
        "risks_analysis": risks,
        "completed_steps": ["strategy_risk"],
        "worker_summaries": [{
            "worker": "strategy_risk",
            "status": "success",
            "summary": summary
        }]
    }
