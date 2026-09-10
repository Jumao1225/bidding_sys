"""主 Agent 提示词策略测试。"""

from unittest.mock import MagicMock, patch

from app.agents.supervisor import build_master_agent_prompt
from app.agents.orchestrator import supervisor_node


def test_build_master_agent_prompt_should_not_retry_for_null_result() -> None:
    """业务字段为 null 时，提示词应要求主 Agent 接受首次结果。"""

    prompt = build_master_agent_prompt(document_id="doc-1", toc_str="第一章 总则")

    assert "必须直接接受该结果" in prompt
    assert "`null`、空数组、字段缺失" in prompt
    assert "严禁仅因这些数据内容再次调用同一工具" in prompt
    assert "发现核心字段为 null" not in prompt


def test_build_master_agent_prompt_should_allow_only_transient_error_retry() -> None:
    """只有明确的暂时性执行错误才应保留重试空间。"""

    prompt = build_master_agent_prompt(document_id="doc-1", toc_str="第一章 总则")

    assert "明确的执行错误" in prompt
    assert "暂时性调用失败" in prompt
    assert "不得把业务字段内容当成失败依据" in prompt


def test_supervisor_node_should_not_dispatch_completed_worker_again() -> None:
    """Worker 已完成时，即使模型重复返回其名称，也不能再次派发。"""
    decision = MagicMock(next=["strategy_risk"], reasoning="重复返回的测试决策")
    state = {
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "completed_steps": ["strategy_risk"],
        "running_steps": ["strategy_risk"],
        "retry_counts": {},
        "worker_summaries": [{"worker": "strategy_risk", "status": "failed"}],
    }

    with patch("app.agents.orchestrator.llm_service.generate_structured_output", return_value=decision), \
         patch("app.worker.tasks.emit_agent_log"):
        result = supervisor_node(state)

    assert result["next"] == []
    assert result["running_steps"] == []
