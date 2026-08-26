"""原文件下载接口的回归测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.api import deps
from app.api.endpoints import analysis
from app.main import app


@pytest.mark.asyncio
async def test_download_original_file_should_find_file_in_tenders_directory():
    """任务 ID 预览应能读取 uploads/tenders 中尚未建档的原始 PDF。"""
    task_id = "preview-task-test-001"
    upload_dir = Path(__file__).resolve().parents[2] / "uploads" / "tenders"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_file = upload_dir / f"{task_id}_测试原文件.pdf"
    upload_file.write_bytes(b"%PDF-1.4\npreview test\n")

    mock_db = MagicMock()
    app.dependency_overrides[analysis.get_db] = lambda: mock_db
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    try:
        transport = httpx.ASGITransport(app=app)
        with patch(
            "app.db.crud.document.document_crud.get_document_by_id_system",
            return_value=None,
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/v1/analysis/download/{task_id}")

        assert response.status_code == 200
        assert response.content == b"%PDF-1.4\npreview test\n"
        assert response.headers["content-type"] == "application/pdf"
    finally:
        app.dependency_overrides.clear()
        upload_file.unlink(missing_ok=True)
