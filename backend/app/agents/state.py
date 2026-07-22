from typing import TypedDict, List, Dict, Any, Annotated
import operator

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
    
    # --- Supervisor 调度所需 (新增) ---
    next: List[str]                # Supervisor 决定的下一步节点名数组（支持并发）
    dispatched_steps: Annotated[list, operator.add]  # 已派发步骤（用于计算 running_steps）
    completed_steps: Annotated[list, operator.add]   # 已完成步骤
    worker_summaries: Annotated[list, operator.add]  # Worker 执行摘要
    retry_counts: Dict[str, int]   # 各节点重试次数（上限 2 次）

    # 状态控制
    status: str
    error: str
