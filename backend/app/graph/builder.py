from langgraph.graph import StateGraph, END
from app.agents.state import BiddingState
from app.agents.nodes.parser_worker import parser_worker_node
from app.agents.supervisor import master_agent_node
from app.agents.nodes.strategy_agent import analyze_qualifications_node, identify_risks_node
from app.agents.nodes.cost_agent import cost_node
from app.agents.orchestrator import supervisor_node
from app.agents.nodes.writer_agent_node import writer_agent_node

def route_after_parser(state: BiddingState) -> str:
    """如果解析节点失败，直接终止编排图，否则进入 Supervisor 调度"""
    if state.get("status") == "parser_failed":
        return END
    return "supervisor"

from typing import List

def route_from_supervisor(state: BiddingState) -> List[str]:
    """Supervisor 决策路由 (支持并发)"""
    nxt = state.get("next", ["FINISH"])
    if not isinstance(nxt, list):
        nxt = [nxt]
        
    routes = []
    for n in nxt:
        if n == "FINISH":
            routes.append(END)
        elif n != "WAIT":
            routes.append(n)
            
    return routes

def build_bidding_graph():
    """
    构建总控编排图 (Hub-and-Spoke 拓扑)
    """
    builder = StateGraph(BiddingState)
    
    # 注册所有节点
    builder.add_node("parser_worker", parser_worker_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("master_agent", master_agent_node)
    builder.add_node("strategy_qual", analyze_qualifications_node)
    builder.add_node("strategy_risk", identify_risks_node)
    builder.add_node("cost_estimation", cost_node)
    builder.add_node("writer_agent", writer_agent_node)
    
    # 构建边 (入口)
    builder.set_entry_point("parser_worker")
    builder.add_conditional_edges("parser_worker", route_after_parser, ["supervisor", END])
    
    # Supervisor 动态路由 (核心 Hub)
    builder.add_conditional_edges("supervisor", route_from_supervisor, {
        "master_agent": "master_agent",
        "strategy_qual": "strategy_qual",
        "strategy_risk": "strategy_risk",
        "cost_estimation": "cost_estimation",
        "writer_agent": "writer_agent",
        END: END
    })
    
    # 所有 Worker 执行完，无条件汇报回 Supervisor (Spokes to Hub)
    builder.add_edge("master_agent", "supervisor")
    builder.add_edge("strategy_qual", "supervisor")
    builder.add_edge("strategy_risk", "supervisor")
    builder.add_edge("cost_estimation", "supervisor")
    builder.add_edge("writer_agent", "supervisor")
    
    # 编译成可执行的图
    return builder.compile()

# 提供一个全局单例供 Celery / BackgroundTasks 调用
bidding_graph = build_bidding_graph()
