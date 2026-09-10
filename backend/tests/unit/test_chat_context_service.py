"""ChatAgent 会话上下文和国内模型能力识别的单元测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.chat_context_service import ChatContextManager
from app.services.model_capabilities import ModelCapabilities, resolve_model_capabilities


def test_estimate_tokens_should_return_zero_for_empty_text() -> None:
    """边界场景：空文本不应产生虚假的上下文 token。"""
    assert ChatContextManager.estimate_tokens("") == 0


def test_estimate_tokens_should_handle_mixed_chinese_and_english() -> None:
    """正常场景：中英文混合文本应返回稳定的正数估算值。"""
    estimated_tokens = ChatContextManager.estimate_tokens("投标文件 budget 2026")

    assert estimated_tokens > 0
    assert estimated_tokens == ChatContextManager.estimate_tokens("投标文件 budget 2026")


def test_build_messages_should_restore_summary_and_incremental_messages() -> None:
    """正常场景：模型输入应包含摘要、checkpoint 后消息和当前问题。"""
    checkpoint = SimpleNamespace(
        strategy="summary",
        upto_sequence=2,
        payload={"task_goal": "核对交货期", "pending_items": ["确认付款节点"]},
    )
    persisted_messages = [
        SimpleNamespace(
            role="assistant",
            content="交货期为原文要求的期限",
            provider_payload_json={"reasoning_content": "已保留的推理字段"},
        ),
        SimpleNamespace(role="user", content="还需要核对付款节点"),
    ]
    session = SimpleNamespace(id="session-1")

    with patch(
        "app.services.chat_context_service.chat_session_service.get_latest_checkpoint",
        return_value=checkpoint,
    ), patch(
        "app.services.chat_context_service.chat_session_service.list_messages",
        return_value=persisted_messages,
    ) as list_messages:
        messages = ChatContextManager.build_messages(
            db=SimpleNamespace(),
            session=session,
            system_prompt="你是招投标助手",
            question="请给出下一步建议",
        )

    assert len(messages) == 5
    assert "历史会话摘要" in messages[1].content
    assert messages[2].content == "交货期为原文要求的期限"
    assert messages[2].additional_kwargs["reasoning_content"] == "已保留的推理字段"
    assert messages[-1].content == "请给出下一步建议"
    list_messages.assert_called_once_with(SimpleNamespace(), session, after_sequence=2)


def test_maybe_compact_should_keep_recent_messages_outside_summary(monkeypatch) -> None:
    """边界场景：触发压缩时应保留配置数量的最近消息。"""
    monkeypatch.setattr("app.services.chat_context_service.settings.CHAT_CONTEXT_SUMMARY_TRIGGER_TOKENS", 1)
    monkeypatch.setattr("app.services.chat_context_service.settings.CHAT_CONTEXT_KEEP_RECENT_MESSAGES", 1)
    db = SimpleNamespace()
    session = SimpleNamespace(id="session-1")
    messages = [
        SimpleNamespace(sequence=1, role="user", content="历史问题", sources_json=[]),
        SimpleNamespace(sequence=2, role="assistant", content="历史回答", sources_json=[]),
    ]
    db_context = MagicMock()
    db_context.__enter__.return_value = db

    with patch("app.services.chat_context_service.SessionLocal", return_value=db_context), patch(
        "app.services.chat_context_service.chat_session_service.get_owned_session",
        return_value=session,
    ), patch(
        "app.services.chat_context_service.chat_session_service.get_latest_checkpoint",
        return_value=None,
    ), patch(
        "app.services.chat_context_service.chat_session_service.list_messages",
        return_value=messages,
    ), patch.object(
        ChatContextManager,
        "_generate_summary",
        return_value={"task_goal": "", "confirmed_facts": [], "completed_work": [], "decisions": [], "tool_results": [], "citations": [], "pending_items": [], "next_steps": []},
    ) as generate_summary, patch.object(
        ChatContextManager,
        "_resolve_capabilities",
        return_value=(ModelCapabilities(provider="deepseek"), "deepseek-chat"),
    ), patch(
        "app.services.chat_context_service.chat_session_service.save_summary_checkpoint",
    ) as save_checkpoint:
        ChatContextManager.maybe_compact(
            session_id="session-1",
            tenant_id="tenant-1",
            user_id="user-1",
            document_id="document-1",
            system_prompt="系统规则",
        )

    generate_summary.assert_called_once()
    assert generate_summary.call_args.kwargs["messages"] == [
        {"sequence": 1, "role": "user", "content": "历史问题", "sources": []}
    ]
    assert save_checkpoint.call_args.kwargs["upto_sequence"] == 1


def test_resolve_model_capabilities_should_preserve_deepseek_reasoning_fields() -> None:
    """正常场景：DeepSeek 工具调用路径必须保留后续请求所需的推理字段。"""
    capabilities = resolve_model_capabilities("deepseek-chat", "https://api.deepseek.com")

    assert capabilities.provider == "deepseek"
    assert capabilities.protocol == "chat_completions"
    assert capabilities.preserve_reasoning_fields is True
    assert capabilities.supports_native_compaction is False


def test_resolve_model_capabilities_should_recognize_glm_model() -> None:
    """正常场景：GLM-5.3 应归入国内 Chat Completions 能力档案。"""
    capabilities = resolve_model_capabilities("glm-5.3", "https://open.bigmodel.cn/api/paas/v4")

    assert capabilities.provider == "glm"
    assert capabilities.supports_tools is True
    assert capabilities.supports_json_output is True


def test_resolve_model_capabilities_should_use_conservative_default_for_unknown_model() -> None:
    """异常配置场景：未知兼容模型不能误判为支持原生 compaction。"""
    capabilities = resolve_model_capabilities("custom-model", "https://llm.example.com/v1")

    assert capabilities.provider == "openai_compatible"
    assert capabilities.supports_native_compaction is False
