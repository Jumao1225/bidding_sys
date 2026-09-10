"""
Bid Generator API 接口测试 (test_bid_generator_api.py)

测试 /api/v1/bidding/extract-bid-format/{document_id} 接口的认证拦截、异常捕获与正常二进制 Word 响应。
"""

import asyncio
import time
import pytest
import httpx
import inspect
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, mock_open
from app.main import app
from app.api.deps import get_current_active_user, get_current_user_optional, get_db
from app.api.endpoints.bid_generator import _get_bid_fill_pipeline_state, get_bid_fill_worker_logs
from app.services.bid_fill_task_service import BidFillTaskReservation


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
async def test_extract_bid_format_api_model_unavailable_should_return_503():
    """模型服务不可用时，接口应返回明确的 503 提示而不是下载基础模板。"""
    from app.services.llm_service import ModelUnavailableError

    mock_user = MagicMock()
    mock_user.id = "user-test-bid"
    mock_user.tenant_id = "tenant-test-bid"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            side_effect=ModelUnavailableError("模型不可用：模型服务连接失败"),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/extract-bid-format/doc-12345")
                assert res.status_code == 503
                assert "模型不可用" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_extract_bid_format_api_should_force_reextract_template():
    """重新提取接口应跳过缓存并显式传递强制提取标志。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            return_value=(b"PK\x03\x04template", "测试模板.docx", "native_docx"),
        ) as extractor:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/extract-bid-format/doc-12345")

            assert res.status_code == 200
            assert extractor.call_args.kwargs["force_reextract"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reextract_bid_format_api_should_refresh_template_without_download():
    """重新提取接口应刷新缓存并返回状态信息，不直接返回 Word 二进制流。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            return_value=(b"PK\x03\x04template", "测试模板.docx", "native_docx"),
        ) as extractor:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post("/api/v1/bidding/reextract-bid-format/doc-12345")

            assert res.status_code == 200
            assert res.json()["message"] == "投标文件模板重新提取成功"
            assert extractor.call_args.kwargs["force_reextract"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_bid_format_template_api_should_use_cached_or_first_extract_flow():
    """下载模板接口应使用非强制提取流程，由服务层决定命中缓存或首次提取。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            return_value=(b"PK\x03\x04template", "测试模板.docx", "cached_native_docx"),
        ) as extractor:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.get("/api/v1/bidding/download-bid-format-template/doc-12345")

            assert res.status_code == 200
            assert res.content == b"PK\x03\x04template"
            assert extractor.call_args.kwargs["force_reextract"] is False
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
async def test_download_agent_filled_bid_format_without_result_should_return_conflict():
    """未生成填报结果时，下载接口应提示先填写且不得启动 Agent。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    mock_db = MagicMock()
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            "app.api.endpoints.bid_generator._has_non_empty_result_file",
            return_value=False,
        ), patch(
            "app.agents.bid_filler_agent.bid_filler_agent.process_filling_tasks"
        ) as process_filling_tasks:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get(
                    "/api/v1/bidding/agent-fill-bid-format/doc-not-filled/download"
                )

        assert response.status_code == 409
        assert "先填写标书" in response.json()["detail"]
        process_filling_tasks.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_agent_filled_bid_format_existing_result_should_return_cached_docx():
    """已生成非空结果文件时，下载接口应直接返回缓存文件而不重复撰写。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    mock_db = MagicMock()
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    result_bytes = b"cached-filled-docx"

    try:
        with patch(
            "app.api.endpoints.bid_generator._has_non_empty_result_file",
            return_value=True,
        ), patch(
            "builtins.open",
            mock_open(read_data=result_bytes),
        ), patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            return_value=(b"template", "测试项目.docx", "bound_external_template"),
        ), patch(
            "app.agents.bid_filler_agent.bid_filler_agent.process_filling_tasks"
        ) as process_filling_tasks:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get(
                    "/api/v1/bidding/agent-fill-bid-format/doc-cache/download"
                )

        assert response.status_code == 200
        assert response.content == result_bytes
        process_filling_tasks.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
async def test_deprecated_human_fill_endpoints_should_return_404(method: str) -> None:
    """验证已废弃的人工填报接口不再对外暴露。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await getattr(
            async_client,
            method,
        )("/api/v1/bidding/human-fill-bid-format/doc-legacy")

    assert response.status_code == 404


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
            assert data["manual_chapters"] == []
            assert data["manual_pending_count"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_bid_template_binding_should_return_current_binding():
    """查询当前文档模板绑定时应返回租户范围内的 active 绑定。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    binding = SimpleNamespace(
        id="binding-1",
        document_id="doc-1",
        template_id="template-1",
        status="active",
        note=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.services.bid_template_service.bid_template_service.get_binding",
            return_value=binding,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/bidding/template-bindings/doc-1")

        assert response.status_code == 200
        assert response.json()["data"]["template_id"] == "template-1"
        assert response.json()["data"]["status"] == "active"
    finally:
        app.dependency_overrides.clear()


def test_get_bid_fill_worker_logs_route_should_run_outside_event_loop():
    """同步数据库查询路由必须交给 FastAPI 线程池，不能阻塞主事件循环。"""
    assert inspect.iscoroutinefunction(get_bid_fill_worker_logs) is False


@pytest.mark.asyncio
async def test_trigger_agent_bid_filling_available_slot_should_start_isolated_process():
    """可用槽位下应启动独立进程，不在 API 进程执行标书撰写。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    mock_db = MagicMock()
    reservation = BidFillTaskReservation(
        document_lock_key="bid-fill:document:doc-12345",
        capacity_lock_key="bid-fill:capacity:0",
        token="reservation-token",
    )
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    selected_profile_id = "profile-sichuan-shinan"

    try:
        with patch(
            "app.services.bid_fill_task_service.bid_fill_task_service.acquire",
            return_value=(reservation, "accepted"),
        ), patch(
            "app.services.bid_fill_task_service.start_bid_fill_process",
            return_value=24680,
        ) as start_process:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/api/v1/bidding/agent-fill-bid-format/doc-12345",
                    json={"profile_id": selected_profile_id},
                )

        assert response.status_code == 200
        assert response.json()["task_id"] == "process-24680"
        assert response.json()["process_id"] == 24680
        start_process.assert_called_once()
        assert start_process.call_args.kwargs["profile_id"] == selected_profile_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_agent_bid_filling_duplicate_document_should_return_conflict():
    """同一文档已有运行任务时，接口应返回 409 而非重复派发。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user

    try:
        with patch(
            "app.services.bid_fill_task_service.bid_fill_task_service.acquire",
            return_value=(None, "document_running"),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post("/api/v1/bidding/agent-fill-bid-format/doc-12345")

        assert response.status_code == 409
        assert "正在撰写中" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_agent_bid_filling_slow_dispatch_should_not_block_health_check():
    """模拟 Windows 子进程启动较慢时，健康检查仍应及时返回。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    def slow_start_process(**kwargs):
        """模拟真实环境下的同步进程启动开销。"""
        time.sleep(0.25)
        return 24681

    try:
        with patch(
            "app.services.bid_fill_task_service.bid_fill_task_service.acquire",
            return_value=(
                BidFillTaskReservation(
                    document_lock_key="bid-fill:document:doc-slow-dispatch",
                    capacity_lock_key="bid-fill:capacity:0",
                    token="reservation-token",
                ),
                "accepted",
            ),
        ), patch(
            "app.services.bid_fill_task_service.start_bid_fill_process",
            side_effect=slow_start_process,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                trigger_task = asyncio.create_task(
                    ac.post("/api/v1/bidding/agent-fill-bid-format/doc-slow-dispatch")
                )
                await asyncio.sleep(0.03)

                health_started = time.perf_counter()
                health_response = await ac.get("/health")
                health_elapsed = time.perf_counter() - health_started
                trigger_response = await trigger_task

        assert trigger_response.status_code == 200
        assert health_response.status_code == 200
        assert health_elapsed < 0.20
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_agent_download_without_result_should_return_conflict_without_restarting_filler():
    """结果文件不存在时，下载接口应立即返回冲突，不得再次启动完整标书撰写。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch(
            "app.api.endpoints.bid_generator._has_non_empty_result_file",
            return_value=False,
        ), patch(
            "app.agents.bid_filler_agent.bid_filler_agent.process_filling_tasks",
        ) as process_filling_tasks:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get(
                    "/api/v1/bidding/agent-fill-bid-format/doc-download-pending/download"
                )

        assert response.status_code == 409
        assert "后台撰写中" in response.json()["detail"] or "尚未生成" in response.json()["detail"]
        process_filling_tasks.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_agent_download_slow_result_read_should_not_block_health_check():
    """读取已生成结果较慢时，健康检查仍应及时返回。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    def slow_read_result(*args, **kwargs):
        """模拟结果文件读取和文件名查询的同步耗时。"""
        time.sleep(0.25)
        return b"PK\x03\x04DummyFilledDocx", "【ReActAgent智能填报】测试.docx"

    try:
        with patch(
            "app.api.endpoints.bid_generator._has_non_empty_result_file",
            return_value=True,
        ), patch(
            "app.api.endpoints.bid_generator._read_agent_result_file",
            side_effect=slow_read_result,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                download_task = asyncio.create_task(
                    ac.get("/api/v1/bidding/agent-fill-bid-format/doc-download-ready/download")
                )
                await asyncio.sleep(0.03)

                health_started = time.perf_counter()
                health_response = await ac.get("/health")
                health_elapsed = time.perf_counter() - health_started
                download_response = await download_task

        assert download_response.status_code == 200
        assert download_response.content == b"PK\x03\x04DummyFilledDocx"
        assert health_response.status_code == 200
        assert health_elapsed < 0.20
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bid_fill_audit_report_slow_generation_should_not_block_health_check():
    """审计报告触发的长耗时生成应在线程池执行，不能阻塞其他接口。"""
    mock_user = MagicMock(id="user-test-bid", tenant_id="tenant-test-bid")
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {
        "document_id": "doc-audit-slow",
        "total_fields_count": 0,
        "audit_items": [],
        "review_findings": [],
        "review_summary": "",
        "manual_chapters": [],
        "manual_pending_count": 0,
        "summary_note": "",
    }
    app.dependency_overrides[get_current_user_optional] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: MagicMock()

    def slow_audit_generation(**kwargs):
        """模拟审计报告内部再次执行 Agent 的耗时。"""
        time.sleep(0.25)
        return {}, mock_report, None

    try:
        with patch(
            "app.services.bid_format_extractor_service.bid_format_extractor_service.extract_and_export_bid_format",
            return_value=(b"PK\\x03\\x04Template", "测试项目.docx", "native_docx"),
        ), patch(
            "app.agents.bid_filler_agent.bid_filler_agent.process_filling_tasks",
            side_effect=slow_audit_generation,
        ), patch(
            "app.api.endpoints.bid_generator.get_bid_fill_worker_logs",
            return_value={"worker_items": [], "total_workers_count": 0, "manual_chapters": [], "manual_pending_count": 0},
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                audit_task = asyncio.create_task(
                    ac.get("/api/v1/bidding/fill-bid-format/doc-audit-slow/audit-report")
                )
                await asyncio.sleep(0.03)

                health_started = time.perf_counter()
                health_response = await ac.get("/health")
                health_elapsed = time.perf_counter() - health_started
                audit_response = await audit_task

        assert audit_response.status_code == 200
        assert health_response.status_code == 200
        assert health_elapsed < 0.20
    finally:
        app.dependency_overrides.clear()


def test_bid_fill_pipeline_state_should_stay_processing_after_intermediate_supervisor_success():
    """中间 Supervisor 成功但最终终态未写入时，不应提前判定整条流程完成。"""
    now = datetime.now()
    logs = [
        SimpleNamespace(node_name="Supervisor-总控调度", status="in_progress", created_at=now),
        SimpleNamespace(node_name="Supervisor-Orchestrator", status="success", created_at=now + timedelta(seconds=1)),
        SimpleNamespace(node_name="BidFillerWorker-项目负责人", status="success", created_at=now + timedelta(seconds=2)),
    ]

    state = _get_bid_fill_pipeline_state(logs)

    assert state["pipeline_status"] == "processing"
    assert state["is_completed"] is False


def test_bid_fill_pipeline_state_should_complete_only_after_final_supervisor_log():
    """只有后台最终 Supervisor master_completed 才能结束前端轮询。"""
    now = datetime.now()
    logs = [
        SimpleNamespace(node_name="Supervisor-Orchestrator", status="success", created_at=now),
        SimpleNamespace(node_name="Supervisor-总控调度", status="master_completed", created_at=now + timedelta(seconds=3)),
    ]

    state = _get_bid_fill_pipeline_state(logs)

    assert state["pipeline_status"] == "completed"
    assert state["is_completed"] is True


def test_bid_fill_pipeline_state_should_mark_failed_terminal_log():
    """最终 Supervisor failed 时应结束轮询并向前端返回失败状态。"""
    state = _get_bid_fill_pipeline_state([
        SimpleNamespace(node_name="Supervisor-总控调度", status="failed", created_at=datetime.now())
    ])

    assert state["pipeline_status"] == "failed"
    assert state["is_completed"] is True


def test_bid_fill_pipeline_state_should_expose_model_service_unavailable_message():
    """模型连接失败时，终态快照应向前端返回明确的模型服务不可用提示。"""
    state = _get_bid_fill_pipeline_state([
        SimpleNamespace(
            node_name="Supervisor-总控调度",
            status="failed",
            created_at=datetime.now(),
            outputs={"summary": "❌ 后台标书撰写任务异常中断: 模型不可用：模型服务连接失败，请检查模型地址、网络或服务状态"},
            error_message=None,
        )
    ])

    assert state["pipeline_status"] == "failed"
    assert state["pipeline_message"] == "模型服务不可用：模型服务连接失败，请检查模型地址、网络或服务状态"
    assert state["is_completed"] is True
