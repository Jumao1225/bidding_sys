from langgraph.graph import StateGraph, END
from app.agents.state import BiddingState
from app.agents.nodes.strategy_agent import analyze_qualifications_node, identify_risks_node
from app.agents.nodes.cost_agent import cost_node

def build_bidding_graph():
    """
    构建总控编排图
    """
    builder = StateGraph(BiddingState)
    
    # 注册节点
    builder.add_node("analyze_qualifications", analyze_qualifications_node)
    builder.add_node("identify_risks", identify_risks_node)
    builder.add_node("cost_estimation", cost_node)
    
    # 构建边 (这里简单串行，实际可按需并行)
    builder.set_entry_point("analyze_qualifications")
    builder.add_edge("analyze_qualifications", "identify_risks")
    builder.add_edge("identify_risks", "cost_estimation")
    builder.add_edge("cost_estimation", END)
    
    # 编译成可执行的图
    return builder.compile()

# 提供一个全局单例供 Celery Worker 调用
bidding_graph = build_bidding_graph()
