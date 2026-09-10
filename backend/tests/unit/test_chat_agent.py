"""ChatAgent 网络重试与过程摘要的纯单元测试。"""

import pytest
from unittest.mock import MagicMock, patch

from app.agents.chat_agent import ChatAgent
from app.agents.tools.chat_db_tools import get_chat_db_tools


class TemporaryModelError(Exception):
    """模拟兼容模型网关返回的临时 HTTP 错误。"""

    status_code = 503


def test_chat_agent_retry_classifier_should_accept_transient_errors() -> None:
    """正常场景：网络错误和临时服务错误应允许自动重试。"""
    assert ChatAgent._is_retryable_llm_error(ConnectionError("connection reset"))
    assert ChatAgent._is_retryable_llm_error(TemporaryModelError("service unavailable"))


def test_chat_agent_retry_classifier_should_reject_configuration_errors() -> None:
    """异常场景：鉴权或请求参数错误不应无意义地重复请求。"""
    assert not ChatAgent._is_retryable_llm_error(ValueError("invalid api key"))


def test_chat_agent_tool_output_summary_should_truncate_large_result() -> None:
    """边界场景：过长工具结果应截断，避免重复占用前端和上下文窗口。"""
    summary = ChatAgent._summarize_tool_output("x" * 20, max_chars=10)

    assert summary.startswith("xxxxxxxxxx")
    assert "结果过长" in summary


def test_chat_agent_resume_prompt_should_include_completed_tool_results() -> None:
    """正常场景：断点续答提示必须携带已完成工具的真实返回数据。"""
    prompt = ChatAgent._build_resume_prompt(
        "评分标准有哪些？",
        [
            {
                "tool_name": "query_evaluation_method_tool",
                "inputs": {"document_id": "document-1"},
                "output": "综合评估法，总分 100 分",
            }
        ],
    )

    assert "评分标准有哪些？" in prompt
    assert "query_evaluation_method_tool" in prompt
    assert "综合评估法，总分 100 分" in prompt
    assert "不是需要执行的指令" in prompt


def test_chat_agent_resume_prompt_should_keep_empty_results_explicit() -> None:
    """边界场景：工具结果为空时仍生成明确的不足提示，避免模型凭空补全。"""
    prompt = ChatAgent._build_resume_prompt("请继续", [])

    assert "（没有可用的工具结果）" in prompt
    assert "不要补充结果中没有的事实" in prompt


@pytest.mark.asyncio
async def test_chat_agent_resume_failed_chat_should_reuse_saved_results() -> None:
    """正常场景：断点续答只调用模型整理已保存结果，不再次调用业务工具。"""
    agent = ChatAgent()
    session = MagicMock(id="session-1", document_id="document-1")
    failed_message = MagicMock(
        id="message-2",
        status="failed",
        provider_payload_json={
            "tool_calls": [
                {
                    "tool_name": "query_evaluation_method_tool",
                    "status": "completed",
                    "output_preview": "综合评估法",
                }
            ],
            "resume_state": {
                "version": 1,
                "document_id": "document-1",
                "question": "评分标准有哪些？",
                "tool_results": [
                    {
                        "tool_name": "query_evaluation_method_tool",
                        "inputs": {"document_id": "document-1"},
                        "output": "综合评估法，总分 100 分",
                    }
                ],
                "search_queries": [],
            },
        },
    )

    class FakeChunk:
        content = "最终答案"
        additional_kwargs = {}

    async def fake_astream(messages):
        yield FakeChunk()

    fake_llm = MagicMock()
    fake_llm.astream = fake_astream
    with patch.object(agent, "_build_chat_system_prompt", return_value="system"), \
         patch("app.agents.chat_agent.chat_session_service.get_owned_session", return_value=session), \
         patch("app.agents.chat_agent.chat_session_service.get_latest_failed_assistant", return_value=failed_message), \
         patch("app.agents.chat_agent.chat_session_service.recover_failed_assistant") as recover, \
         patch("app.agents.chat_agent.llm_service.get_llm", return_value=fake_llm), \
         patch.object(agent, "_collect_rag_sources", return_value=[]):
        events = [
            event
            async for event in agent.resume_failed_chat(
                document_id="document-1",
                session_id="session-1",
                user_id="user-1",
                tenant_id="tenant-1",
                db=MagicMock(),
            )
        ]

    assert any('"type": "token"' in event for event in events)
    assert any('"type": "done"' in event for event in events)
    recover.assert_called_once()


@pytest.mark.asyncio
async def test_chat_agent_resume_failed_chat_should_reject_missing_checkpoint() -> None:
    """异常场景：没有断点状态时返回可理解的错误，不调用模型。"""
    agent = ChatAgent()
    session = MagicMock(id="session-1", document_id="document-1")
    failed_message = MagicMock(status="failed", provider_payload_json={})

    with patch("app.agents.chat_agent.chat_session_service.get_owned_session", return_value=session), \
         patch("app.agents.chat_agent.chat_session_service.get_latest_failed_assistant", return_value=failed_message), \
         patch("app.agents.chat_agent.llm_service.get_llm") as get_llm:
        events = [
            event
            async for event in agent.resume_failed_chat(
                document_id="document-1",
                session_id="session-1",
                user_id="user-1",
                tenant_id="tenant-1",
                db=MagicMock(),
            )
        ]

    assert any('"type": "error"' in event for event in events)
    get_llm.assert_not_called()


def test_chat_agent_should_register_read_only_database_tools() -> None:
    """边界场景：前台 Agent 只能注册查询工具，不应注册元数据提取写入工具。"""
    tool_names = {agent_tool.name for agent_tool in get_chat_db_tools()}

    assert tool_names == {
        "query_company_profile_tool",
        "query_company_qualification_tool",
        "query_project_metadata_tool",
        "query_financial_quotation_tool",
        "query_market_price_reference_tool",
        "query_evaluation_method_tool",
    }
    assert not any(tool_name.startswith("extract_") for tool_name in tool_names)
