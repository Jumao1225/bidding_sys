"""
聊天 API 接口单元测试 (Chat API Tests)

测试 Chat API 接口的入参校验、文档存在性校验与 SSE 流式接口响应。
"""
import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user
from app.api.endpoints import chat as chat_endpoint

@pytest.mark.asyncio
async def test_chat_empty_question_should_return_422_or_400():
    """测试发送空提问时接口拦截逻辑"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/chat/",
                json={"document_id": "doc-123", "question": "   ", "history": []}
            )
            assert res.status_code == 400
            assert "question 不能为空" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_chat_nonexistent_document_should_return_403():
    """测试提问不存在或无权限的文档时返回 403"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=None):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/chat/",
                    json={"document_id": "nonexistent-doc", "question": "你好", "history": []}
                )
                assert res.status_code == 403
                assert "无权访问此文档" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_chat_valid_document_should_stream_response():
    """测试合法文档提问时成功建立 SSE 响应流"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    mock_session = MagicMock()
    mock_session.id = "session-test-chat"

    async def mock_stream_chat(*args, **kwargs):
        yield 'data: {"type": "token", "content": "您好"}\n\n'
        yield 'data: {"type": "done", "sources": []}\n\n'

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=MagicMock()), \
             patch("app.api.endpoints.chat.chat_session_service.get_owned_session", return_value=mock_session), \
             patch("app.agents.chat_agent.chat_agent.stream_chat", side_effect=mock_stream_chat):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/chat/",
                    json={
                        "document_id": "valid-doc-123",
                        "question": "这本标书的预算是多少",
                        "session_id": "session-test-chat",
                    }
                )
                assert res.status_code == 200
                assert "text/event-stream" in res.headers.get("content-type", "")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resume_failed_chat_should_stream_response_without_new_question():
    """测试断点续答接口能够复用现有会话并建立 SSE 流。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    mock_session = MagicMock()
    mock_session.id = "session-test-chat"
    mock_session.document_id = "valid-doc-123"

    async def mock_resume_failed_chat(*args, **kwargs):
        yield 'data: {"type": "agent_status", "message": "正在继续生成"}\n\n'
        yield 'data: {"type": "done", "sources": []}\n\n'

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.api.endpoints.chat.chat_session_service.get_owned_session", return_value=mock_session), \
             patch("app.agents.chat_agent.chat_agent.resume_failed_chat", side_effect=mock_resume_failed_chat):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/chat/sessions/session-test-chat/resume")

        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        assert '"type": "done"' in res.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_chat_session_should_migrate_history_and_return_session():
    """测试创建会话接口能够返回统一响应并触发旧 history 迁移。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    mock_session = MagicMock()
    mock_session.id = "session-created-chat"
    mock_session.document_id = "valid-doc-123"
    mock_session.title = "历史问题"
    mock_session.status = "active"
    mock_session.active_provider = "deepseek"
    mock_session.active_model = "deepseek-chat"
    mock_session.context_format_version = "v1"
    mock_session.parent_session_id = None
    mock_session.created_at = datetime.now(timezone.utc)
    mock_session.updated_at = mock_session.created_at
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[chat_endpoint.get_db] = lambda: MagicMock()

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=MagicMock()), \
             patch("app.api.endpoints.chat.chat_session_service.create_session", return_value=mock_session), \
             patch("app.api.endpoints.chat.chat_session_service.import_legacy_history", return_value=2) as import_history:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/chat/sessions",
                    json={
                        "document_id": "valid-doc-123",
                        "history": [
                            {"role": "user", "content": "历史问题"},
                            {"role": "ai", "content": "历史回答"},
                        ],
                    },
                )

        assert res.status_code == 200
        assert res.json()["data"]["id"] == "session-created-chat"
        import_history.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_chat_session_should_soft_delete_owned_session():
    """正常场景：删除有权访问的会话应调用软删除服务并返回成功。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_session = MagicMock()
    mock_session.id = "session-delete-chat"
    mock_session.document_id = "valid-doc-123"
    mock_session.title = "待删除会话"
    mock_session.status = "deleted"
    mock_session.active_provider = None
    mock_session.active_model = None
    mock_session.context_format_version = "v1"
    mock_session.parent_session_id = None
    mock_session.created_at = datetime.now(timezone.utc)
    mock_session.updated_at = mock_session.created_at

    try:
        transport = httpx.ASGITransport(app=app)
        with patch(
            "app.api.endpoints.chat.chat_session_service.get_owned_session",
            return_value=mock_session,
        ), patch(
            "app.api.endpoints.chat.chat_session_service.delete_session",
            return_value=mock_session,
        ) as delete_session:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.delete("/api/v1/chat/sessions/session-delete-chat")

        assert response.status_code == 200
        assert response.json()["message"] == "会话已删除"
        delete_session.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_foreign_chat_session_should_return_403():
    """异常场景：删除不属于当前用户的会话必须被拒绝。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    try:
        transport = httpx.ASGITransport(app=app)
        with patch(
            "app.api.endpoints.chat.chat_session_service.get_owned_session",
            return_value=None,
        ), patch(
            "app.api.endpoints.chat.chat_session_service.delete_session",
        ) as delete_session:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.delete("/api/v1/chat/sessions/foreign-session")

        assert response.status_code == 403
        delete_session.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_with_foreign_session_should_return_403():
    """测试传入不属于当前用户或文档的会话时禁止启动 Agent。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-chat"
    mock_user.tenant_id = "tenant-test-chat"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=MagicMock()), \
             patch("app.api.endpoints.chat.chat_session_service.get_owned_session", return_value=None):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/chat/",
                    json={
                        "document_id": "valid-doc-123",
                        "session_id": "foreign-session",
                        "question": "请继续回答",
                    },
                )

        assert res.status_code == 403
        assert "会话" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()
