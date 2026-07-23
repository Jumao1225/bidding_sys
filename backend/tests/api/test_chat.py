"""
聊天 API 接口单元测试 (Chat API Tests)

测试 Chat API 接口的入参校验、文档存在性校验与 SSE 流式接口响应。
"""
import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user

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

    async def mock_stream_chat(*args, **kwargs):
        yield 'data: {"type": "token", "content": "您好"}\n\n'
        yield 'data: {"type": "done", "sources": []}\n\n'

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=MagicMock()), \
             patch("app.agents.chat_agent.chat_agent.stream_chat", side_effect=mock_stream_chat):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(
                    "/api/v1/chat/",
                    json={"document_id": "valid-doc-123", "question": "这本标书的预算是多少", "history": []}
                )
                assert res.status_code == 200
                assert "text/event-stream" in res.headers.get("content-type", "")
    finally:
        app.dependency_overrides.clear()
