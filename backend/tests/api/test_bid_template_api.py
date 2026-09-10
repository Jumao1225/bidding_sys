"""外部投标模板上传与绑定 API 测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.api.deps import get_current_active_user, get_db
from app.main import app


def _template_stub() -> SimpleNamespace:
    """构造模板接口响应所需的最小 ORM 替身。"""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id="template-1",
        filename="空白模板.docx",
        file_size=1024,
        file_sha256="a" * 64,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        template_type="external_docx",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_upload_bid_template_api_should_return_template_id() -> None:
    """上传接口成功时应返回可供绑定使用的模板 ID。"""
    mock_user = MagicMock(id="user-1", tenant_id="tenant-1")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_template_service.bid_template_service.upload_template",
            return_value=_template_stub(),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/bidding/templates/upload",
                    files={"file": ("空白模板.docx", b"fake-docx", "application/octet-stream")},
                )

        assert response.status_code == 200
        assert response.json()["data"]["id"] == "template-1"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_bid_template_api_should_return_400_for_validation_error() -> None:
    """模板校验失败时应返回 400，不伪装成服务器异常。"""
    mock_user = MagicMock(id="user-1", tenant_id="tenant-1")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_template_service.bid_template_service.upload_template",
            side_effect=ValueError("仅支持上传 .docx 格式的 Word 模板"),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/bidding/templates/upload",
                    files={"file": ("模板.pdf", b"not-docx", "application/pdf")},
                )

        assert response.status_code == 400
        assert "仅支持上传" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bind_bid_template_api_should_return_binding_status() -> None:
    """绑定接口成功时应返回 active 绑定状态。"""
    mock_user = MagicMock(id="user-1", tenant_id="tenant-1")
    mock_binding = SimpleNamespace(
        id="binding-1",
        document_id="document-1",
        template_id="template-1",
        status="active",
        note=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_template_service.bid_template_service.bind_template",
            return_value=mock_binding,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/bidding/template-bindings/document-1",
                    json={"template_id": "template-1"},
                )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "active"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unbind_bid_template_api_should_return_inactive_binding_status() -> None:
    """解除绑定接口成功时应返回 inactive 状态并提示恢复原格式。"""
    mock_user = MagicMock(id="user-1", tenant_id="tenant-1")
    mock_binding = SimpleNamespace(
        id="binding-1",
        document_id="document-1",
        template_id="template-1",
        status="inactive",
        note=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_template_service.bid_template_service.unbind_template",
            return_value=mock_binding,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete(
                    "/api/v1/bidding/template-bindings/document-1",
                )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "inactive"
        assert "原格式" in response.json()["message"]
    finally:
        app.dependency_overrides.clear()
