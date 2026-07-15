import os
import pytest
import httpx
from pathlib import Path
from app.main import app


@pytest.mark.asyncio
async def test_mineru_status_api_should_return_200():
    """
    测试 GET /api/v1/mineru/status 健康诊断接口
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/mineru/status")

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["code"] == 200
    assert res_json["message"] == "成功获取 MinerU 服务状态"
    assert "is_installed" in res_json["data"]


@pytest.mark.asyncio
async def test_mineru_parse_and_preview_api_should_succeed():
    """
    测试上传 test_bidding.docx 到 POST /api/v1/mineru/parse 并通过 GET /preview-md/{task_id} 在线预览 Markdown 内容
    """
    base_dir = Path(__file__).resolve().parent.parent
    word_fixture_path = base_dir / "fixtures" / "test_bidding.docx"
    assert os.path.exists(word_fixture_path), "Word 测试文件不存在"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. 测试文件解析接口
        with open(word_fixture_path, "rb") as f:
            files = {"file": ("test_bidding.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            data = {"parse_mode": "auto"}
            parse_resp = await ac.post("/api/v1/mineru/parse", files=files, data=data)

        assert parse_resp.status_code == 200
        res_json = parse_resp.json()
        assert res_json["code"] == 200
        task_id = res_json["data"]["task_id"]
        markdown_content = res_json["data"]["markdown_content"]
        assert len(markdown_content) > 0
        assert os.path.exists(res_json["data"]["md_file_path"])

        # 2. 测试 Markdown 在线查看接口
        preview_resp = await ac.get(f"/api/v1/mineru/preview-md/{task_id}")
        assert preview_resp.status_code == 200
        assert preview_resp.text == markdown_content
