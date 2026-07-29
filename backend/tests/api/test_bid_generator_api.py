"""
Bid Generator API 接口测试 (test_bid_generator_api.py)

测试 /api/v1/bidding/extract-bid-format/{document_id} 接口的认证拦截、异常捕获与正常二进制 Word 响应。
"""

import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user, get_db


@pytest.mark.asyncio
async def test_extract_bid_format_api_nonexistent_document_should_return_404():
    """测试请求不存在的文档时返回 404 错误"""
    mock_user = MagicMock()
    mock_user.id = "user-test-bid"
    mock_user.tenant_id = "tenant-test-bid"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch("app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format", side_effect=FileNotFoundError("找不到原始招标文件记录")):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/extract-bid-format/nonexistent-doc-id")
                assert res.status_code == 404
                assert "找不到原始招标文件记录" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_extract_bid_format_api_success_should_return_docx_bytes():
    """测试正向流程：成功导出 Word 并返回包含 Content-Disposition 的二进制流 (POST)"""
    mock_user = MagicMock()
    mock_user.id = "user-test-bid"
    mock_user.tenant_id = "tenant-test-bid"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    dummy_bytes = b"PK\x03\x04DummyDocxFileStream"

    try:
        with patch("app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format", return_value=(dummy_bytes, "测试项目_投标文件格式模板.docx", "native_docx")):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/extract-bid-format/doc-12345")
                assert res.status_code == 200
                assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                assert "attachment" in res.headers["content-disposition"]
                assert res.content == dummy_bytes
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_extract_bid_format_api_get_method_should_succeed():
    """测试 GET 请求方式在 /api/v1/bidding/extract-bid-format/{document_id} 上正常响应 200"""
    mock_user = MagicMock()
    mock_user.id = "user-test-bid"
    mock_user.tenant_id = "tenant-test-bid"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    dummy_bytes = b"PK\x03\x04DummyDocxFileStream"

    try:
        with patch("app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format", return_value=(dummy_bytes, "测试项目_投标文件格式模板.docx", "native_docx")):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.get("/api/v1/bidding/extract-bid-format/doc-12345")
                assert res.status_code == 200
                assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                assert "attachment" in res.headers["content-disposition"]
                assert res.content == dummy_bytes
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_fill_bid_format_api_success_should_return_docx_bytes():
    """测试 Agent 自动填报接口 /api/v1/bidding/fill-bid-format/{document_id} 成功导出 Word"""
    mock_user = MagicMock()
    mock_user.id = "user-test-bid"
    mock_user.tenant_id = "tenant-test-bid"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    dummy_template_bytes = b"PK\x03\x04DummyTemplate"
    dummy_filled_bytes = b"PK\x03\x04DummyFilledDocx"

    mock_report = MagicMock()
    mock_report.total_fields_count = 5
    mock_report.audit_items = []

    try:
        with patch("app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format", return_value=(dummy_template_bytes, "测试项目.docx", "native_docx")), \
             patch("app.services.bid_format_filler_service.bid_format_filler_service.scan_detected_placeholders", return_value=[]), \
             patch("app.agents.bid_filler_agent.bid_filler_agent.process_filling_tasks", return_value=({}, mock_report, dummy_filled_bytes)), \
             patch("app.services.bid_format_filler_service.bid_format_filler_service.fill_docx_with_audit_trail", return_value=dummy_filled_bytes):
            
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/fill-bid-format/doc-12345")
                assert res.status_code == 200
                assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                assert res.content == dummy_template_bytes
    finally:
        app.dependency_overrides.clear()


