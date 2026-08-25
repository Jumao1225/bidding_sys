from sqlalchemy import Column, String, JSON, Integer, Text
from app.db.models.base import TenantBase

class AgentAuditLog(TenantBase):
    """
    智能体运行审计日志表
    记录每次 Agent 流转、LLM 调用及规则拦截的详细过程
    """
    __tablename__ = "agent_audit_logs"

    task_id = Column(String(36), index=True, nullable=False, comment="关联的 Celery/Graph Task ID")
    node_name = Column(String(100), index=True, nullable=False, comment="当前执行节点 (如 StrategyAgent, Supervisor)")
    action_type = Column(String(50), index=True, nullable=False, comment="动作类型: llm_call, tool_call, node_exec, rule_intercept")
    
    # 核心数据
    inputs = Column(JSON, nullable=True, comment="输入参数/提示词 (JSON)")
    outputs = Column(JSON, nullable=True, comment="输出结果/响应内容 (JSON)")
    
    # 消耗与性能
    prompt_tokens = Column(Integer, nullable=True, default=0, comment="提示词 Token")
    completion_tokens = Column(Integer, nullable=True, default=0, comment="补全 Token")
    total_tokens = Column(Integer, nullable=True, default=0, comment="总 Token 消耗")
    execution_time_ms = Column(Integer, nullable=True, comment="节点/调用耗时 (毫秒)")
    
    status = Column(String(20), index=True, nullable=False, default="success", comment="状态: success, error, blocked")
    error_message = Column(Text, nullable=True, comment="错误或拦截原因")
