"""
Agent 行为防护 Guardrails (AgentGuardrails) 单元测试

遵照项目 AGENTS.md 测试规范：
1. 包含正常情况、异常情况与边界情况；
2. 遵循 test_<功能>_<场景>_<期望结果> 命名规范。
"""

import time
import pytest
from app.core.sandbox import AgentGuardrails, SandboxBudgetExceededError


def test_guardrails_step_limit_exceeded_should_raise():
    """异常场景：测试 Agent 工具步数突破 limit 上限触发熔断"""
    guard = AgentGuardrails(max_steps=3)
    
    guard.record_step("tool_a", "arg1")
    guard.record_step("tool_b", "arg2")
    guard.record_step("tool_c", "arg3")
    
    # 第 4 步触发超限熔断
    with pytest.raises(SandboxBudgetExceededError) as exc_info:
        guard.record_step("tool_d", "arg4")
        
    assert "步数超限熔断" in str(exc_info.value)


def test_guardrails_infinite_loop_tool_call_should_raise():
    """异常场景：测试 Agent 连续调用完全相同工具和入参被识别为死循环并终止"""
    guard = AgentGuardrails(max_steps=10, max_repeated_tool_calls=3)
    
    guard.record_step("read_doc", "{'path': 'a.docx'}")
    guard.record_step("read_doc", "{'path': 'a.docx'}")
    
    # 连续第 3 次调完全相同的工具和入参
    with pytest.raises(SandboxBudgetExceededError) as exc_info:
        guard.record_step("read_doc", "{'path': 'a.docx'}")
        
    assert "Agent 死循环死锁熔断" in str(exc_info.value)


def test_guardrails_token_budget_exceeded_should_raise():
    """异常场景：测试 Token 消耗超过预算上限抛出异常"""
    guard = AgentGuardrails(max_tokens=1000)
    guard.record_tokens(400, 400)
    
    with pytest.raises(SandboxBudgetExceededError) as exc_info:
        guard.record_tokens(200, 100)
        
    assert "Token 预算溢出熔断" in str(exc_info.value)


def test_guardrails_execution_timeout_should_raise():
    """边界场景：测试超期运行任务硬超时触发熔断"""
    guard = AgentGuardrails(max_duration_seconds=0.1)
    time.sleep(0.15)
    
    with pytest.raises(SandboxBudgetExceededError) as exc_info:
        guard.check_timeout()
        
    assert "全局超时熔断" in str(exc_info.value)
