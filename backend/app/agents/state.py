from typing import TypedDict, List, Dict, Any

class BiddingState(TypedDict):
    """
    LangGraph 中传递的全局状态 (State)
    """
    # 基础信息
    task_id: str
    document_id: str
    user_id: str
    tenant_id: str
    doc_text: str
    company_quals: str
    
    # 分析结果 (从各节点收集)
    qualifications_analysis: Dict[str, Any]
    risks_analysis: List[Dict[str, Any]]
    cost_analysis: Dict[str, Any]
    
    # 状态控制
    status: str
    error: str
