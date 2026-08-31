import pytest
import httpx
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from app.main import app
from app.api import deps
from app.api.endpoints import mineru as mineru_endpoint


@pytest.fixture
def override_auth():
    """
    重载 FastAPI current_user 鉴权依赖，生成虚拟测试用户进行 API 测试
    """
    mock_user = MagicMock()
    mock_user.id = "user-mineru-tester-101"
    mock_user.tenant_id = "tenant-mineru-unit-999"
    mock_user.is_active = True
    app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_current_user, None)



@pytest.mark.asyncio
async def test_mineru_status_api_should_return_200(override_auth):
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
async def test_mineru_parse_and_preview_api_should_succeed(
    override_auth,
    monkeypatch,
):
    """
    验证真实路由、文件上传、标准响应和 Markdown 预览之间的联调链路。

    云端 MinerU 调用属于不稳定的系统边界，仅在此处替换该边界，避免测试依赖网络。
    """
    base_dir = Path(__file__).resolve().parent.parent
    word_fixture_path = base_dir / "fixtures" / "test_bidding.docx"
    assert word_fixture_path.exists(), "Word 测试文件不存在"

    expected_markdown = "# 联调测试\n\nMinerU API 链路正常。"
    output_base_dir = base_dir / "fixtures" / ".generated_mineru"

    def fake_parse(
        *,
        file_path: str,
        task_id: str,
        parse_mode: str,
    ) -> dict:
        """模拟云端解析边界，同时保留本地文件读写链路。"""
        uploaded_file = Path(file_path)
        assert uploaded_file.exists()
        assert uploaded_file.read_bytes()

        output_dir = output_base_dir / task_id
        output_dir.mkdir(parents=True)
        md_file_path = output_dir / "output.md"
        md_file_path.write_text(expected_markdown, encoding="utf-8")
        return {
            "task_id": task_id,
            "file_name": uploaded_file.name,
            "parse_mode": parse_mode,
            "is_mineru_native": True,
            "md_file_path": str(md_file_path),
            "markdown_content": expected_markdown,
            "page_count": 1,
            "sections": [],
            "images": [],
        }

    monkeypatch.setattr(
        mineru_endpoint.mineru_service,
        "output_base_dir",
        output_base_dir,
    )
    monkeypatch.setattr(mineru_endpoint.mineru_service, "parse", fake_parse)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # 先走真实上传接口，再使用返回的任务 ID 访问预览接口。
        with open(word_fixture_path, "rb") as f:
            files = {"file": ("test_bidding.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            data = {"parse_mode": "auto"}
            parse_resp = await ac.post("/api/v1/mineru/parse", files=files, data=data)

        assert parse_resp.status_code == 200
        res_json = parse_resp.json()
        assert res_json["code"] == 200
        task_id = res_json["data"]["task_id"]
        markdown_content = res_json["data"]["markdown_content"]
        assert markdown_content == expected_markdown
        assert Path(res_json["data"]["md_file_path"]).exists()

        preview_resp = await ac.get(f"/api/v1/mineru/preview-md/{task_id}")
        assert preview_resp.status_code == 200
        assert preview_resp.text == markdown_content

    # 精确清理本用例生成的预览目录，避免测试产物污染仓库。
    shutil.rmtree(output_base_dir / task_id)
    output_base_dir.rmdir()


@pytest.mark.asyncio
async def test_mineru_parse_path_filename_should_use_safe_basename(
    override_auth,
    monkeypatch,
):
    """带路径片段的上传文件名只能以安全 basename 写入临时目录。"""
    captured_file_path: dict[str, Path] = {}

    def fake_parse(
        *,
        file_path: str,
        task_id: str,
        parse_mode: str,
    ) -> dict:
        """记录路由传入解析服务的临时文件路径。"""
        safe_file_path = Path(file_path)
        captured_file_path["value"] = safe_file_path
        return {
            "task_id": task_id,
            "file_name": safe_file_path.name,
            "parse_mode": parse_mode,
            "is_mineru_native": False,
            "md_file_path": str(safe_file_path.with_suffix(".md")),
            "markdown_content": "安全文件名验证",
            "page_count": 1,
            "sections": [],
            "images": [],
        }

    monkeypatch.setattr(mineru_endpoint.mineru_service, "parse", fake_parse)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/mineru/parse",
            files={
                "file": (
                    "..\\unsafe.docx",
                    b"docx-content",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={"parse_mode": "auto"},
        )

    expected_upload_dir = (
        Path(mineru_endpoint.__file__).resolve().parents[3]
        / "uploads"
        / "temp_mineru"
    )
    assert response.status_code == 200
    assert captured_file_path["value"].parent == expected_upload_dir
    assert captured_file_path["value"].name.endswith("_unsafe.docx")


@pytest.mark.asyncio
async def test_mineru_parse_invalid_mode_should_return_422_without_calling_service(
    override_auth,
    monkeypatch,
):
    """无效解析模式应在接口校验层被拒绝，不能触发外部解析服务。"""
    parse_mock = MagicMock()
    monkeypatch.setattr(mineru_endpoint.mineru_service, "parse", parse_mock)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/mineru/parse",
            files={"file": ("sample.pdf", b"%PDF-test", "application/pdf")},
            data={"parse_mode": "unsupported"},
        )

    assert response.status_code == 422
    parse_mock.assert_not_called()


@pytest.mark.asyncio
async def test_mineru_parse_unsupported_file_should_return_400(
    override_auth,
    monkeypatch,
):
    """不支持的文件格式应尽早返回 400，避免无意义的云端请求。"""
    parse_mock = MagicMock()
    monkeypatch.setattr(mineru_endpoint.mineru_service, "parse", parse_mock)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/mineru/parse",
            files={"file": ("sample.txt", b"plain text", "text/plain")},
            data={"parse_mode": "auto"},
        )

    assert response.status_code == 400
    assert "PDF、DOC、DOCX" in response.json()["detail"]
    parse_mock.assert_not_called()


@pytest.mark.asyncio
async def test_mineru_parse_empty_file_should_return_400(
    override_auth,
    monkeypatch,
):
    """空文件属于边界输入，应返回 400 且不调用解析服务。"""
    parse_mock = MagicMock()
    monkeypatch.setattr(mineru_endpoint.mineru_service, "parse", parse_mock)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/mineru/parse",
            files={"file": ("empty.pdf", b"", "application/pdf")},
            data={"parse_mode": "auto"},
        )

    assert response.status_code == 400
    assert "不能为空" in response.json()["detail"]
    parse_mock.assert_not_called()
