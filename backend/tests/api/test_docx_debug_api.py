"""
Docx Debug API 接口测试 (test_docx_debug_api.py)

测试 /api/v1/docx/generate-sample 及 /api/v1/docx/debug-modify 接口：
1. 校验测试模版 Word 导出；
2. 校验接收文件与指令后的原位修改与二进制流响应；
3. 校验非法格式文件拦截。
"""

import io
import pytest
import httpx
from app.main import app
from app.services.docx_test_filler_service import docx_test_filler_service


@pytest.mark.asyncio
async def test_generate_sample_docx_api_should_return_docx_bytes():
    """ 测试 GET /api/v1/docx/generate-sample 成功生成标书测试模版 """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/docx/generate-sample")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert len(res.content) > 0


@pytest.mark.asyncio
async def test_debug_modify_docx_api_should_modify_file_and_return_bytes():
    """ 测试 POST /api/v1/docx/debug-modify 接收上传的 Word 文件与修改指令并正确返回修改后的文件 """
    sample_bytes = docx_test_filler_service.create_sample_docx()

    files = {
        "file": ("test_bidding.docx", sample_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }
    data = {
        "prompt": "项目名称改为无人机协同调度项目，投标人名称改为聚猫机器人"
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/docx/debug-modify", files=files, data=data)
        assert res.status_code == 200
        assert len(res.content) > 0
        assert "Content-Disposition" in res.headers
        assert "X-Modified-Keys" in res.headers


@pytest.mark.asyncio
async def test_debug_modify_docx_api_invalid_file_should_return_400():
    """ 测试上传非 .docx 文件时返回 400 错误 """
    files = {
        "file": ("test.txt", b"hello txt file", "text/plain")
    }
    data = {"prompt": "项目名称改为测试项目"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/docx/debug-modify", files=files, data=data)
        assert res.status_code == 400
        assert "只支持上传 .docx 格式" in res.json()["detail"]
