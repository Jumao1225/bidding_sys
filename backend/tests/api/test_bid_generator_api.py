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


@pytest.mark.asyncio
async def test_get_bidding_documents_list_valid_documents_should_return_list():
    """测试获取招标文件列表 /documents-list 接口成功返回解析好的文档列表"""
    mock_doc = MagicMock()
    mock_doc.id = "doc-test-999"
    mock_doc.filename = "某高标准农田建设项目招标文件.pdf"
    mock_doc.parsed_metadata = {"project_name": "某高标准农田建设项目", "project_code": "XM20260806"}
    mock_doc.created_at = MagicMock()
    mock_doc.created_at.strftime.return_value = "2026-08-06 16:00"

    mock_db = MagicMock()

    try:
        with patch("app.db.crud.document.document_crud.get_all_documents", return_value=[mock_doc]):
            app.dependency_overrides[get_db] = lambda: mock_db
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.get("/api/v1/bidding/documents-list")
                assert res.status_code == 200
                data = res.json()
                assert len(data) == 1
                assert data[0]["id"] == "doc-test-999"
                assert "某高标准农田建设项目" in data[0]["display_label"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_bid_fill_worker_logs_no_logs_should_return_empty_items():
    """测试在文档尚无 Agent 填报履历时调用 worker-logs 接口，安全返回空项目列表而非 500"""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value = mock_query

    try:
        app.dependency_overrides[get_db] = lambda: mock_db
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/v1/bidding/fill-bid-format/doc-empty-logs/worker-logs")
            assert res.status_code == 200
            data = res.json()
            assert data["document_id"] == "doc-empty-logs"
            assert data["total_workers_count"] == 0
            assert data["worker_items"] == []
    finally:
        app.dependency_overrides.clear()



