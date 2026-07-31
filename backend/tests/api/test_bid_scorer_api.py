"""
标书打分系列相关 API 接口自动化单元与集成测试

严格遵循项目定制规则：
1. 本地调试完全采用 httpx.AsyncClient 搭配 ASGITransport 以及 @pytest.mark.asyncio
2. 精确覆盖：正常业务请求情况、服务抛粗或前置规则缺失异常情况、未传合法 ID 的边缘边界情况
3. 一概运用中文标准 Docstring 详细标注阐释核心功能和设计思路
"""

import pytest
import httpx
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.main import app
from app.api.deps import get_current_active_user
from app.db.models.bid_score import BidScoreResult


@pytest.fixture
def override_auth():
    """
    重载 FastAPI current_user 鉴权依赖，生成虚拟默认活动租户用户进行安全冒烟
    """
    mock_user = MagicMock()
    mock_user.id = "user-scorer-tester-101"
    mock_user.tenant_id = "tenant-scorer-unit-999"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_score_bid_api_normal_should_return_success(override_auth):
    """
    正常场景测试：向主打分触发接口提交规范的前后端双写对应 document_id 和 source_doc_id 参数，
    当引擎执行成功完成3轮评分时，能够正常以标准包涵 code、data 的 JSON 结构正确透出总分与分析简易报告。
    """
    mock_service_return = {
        "result_id": "score-result-uuid-888",
        "document_id": "test-bid-doc-id",
        "source_doc_id": "test-source-招标-id",
        "total_score": 92.5,
        "max_possible": 100.0,
        "score_rate": 0.925,
        "category_scores": {"技术分": {"score": 92.5, "max_total": 100.0, "count": 10}},
        "summary": "整体表述条理清楚，方案设计完备...",
        "top_improvements": [],
        "validation_warnings": [],
        "status": "completed",
        "error": "",
    }

    with patch("app.services.bid_scorer_service.bid_scorer_service.score_bid", return_value=mock_service_return):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            payload = {
                "document_id": "test-bid-doc-id",
                "source_doc_id": "test-source-招标-id",
                "scoring_rounds": 3
            }
            resp = await ac.post("/api/v1/bid-scorer/score", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 200
        assert data["message"] == "AI 打分完成"
        assert data["data"]["total_score"] == 92.5
        assert data["data"]["result_id"] == "score-result-uuid-888"


@pytest.mark.asyncio
async def test_score_bid_api_service_failed_should_return_error_response(override_auth):
    """
    异常情况测试：当系统因对应标书缺少必备底稿信息（如上游未曾启动规则抽取）导致状态打标为 failed，
    系统不应随意宕机或报错无说明 500，应由统一规范返回错误响应并携原错误根源解释信息输出。
    """
    mock_fail_return = {
        "status": "failed",
        "error": "关联的招标文件未完成评分维度提取",
    }

    with patch("app.services.bid_scorer_service.bid_scorer_service.score_bid", return_value=mock_fail_return):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            payload = {
                "document_id": "empty-bid-doc-id",
                "source_doc_id": "invalid-source-id",
                "scoring_rounds": 3
            }
            resp = await ac.post("/api/v1/bid-scorer/score", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        # 验证返回标准化报错码以及精准中文诊断原因
        assert data["code"] == 500
        assert "打分失败" in data["message"]
        assert "未完成评分维度提取" in data["message"]


@pytest.mark.asyncio
async def test_get_latest_score_api_not_found_should_return_404(override_auth):
    """
    异常情况与未命中策略测试：针对没有任何历史计算得分记录的有效文档查询最新战报时，
    接口不能奔溃或吐露空值对象，须主动反馈标准 HTTP 404 与合理友好的引导错误提示。
    """
    with patch("app.db.crud.bid_score.bid_score_crud.get_latest_score", return_value=None), \
         patch("app.api.endpoints.bid_scorer.get_db"):
        
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/bid-scorer/results/non-existent-doc-999/latest")

        assert resp.status_code == 404
        assert "暂无打分记录" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_bid_api_missing_or_empty_source_doc_id_should_return_400(override_auth):
    """
    边界情况与 Defensive Programming 拦截测试（尽早返回原则）：
    当调用方的 /upload-bid 前端请求里，没有附送合法非空、关联打分维度的源文件 ID (source_doc_id)，
    服务器不应该去无谓加载存储文件而是直接由控制器果断中断返回 400 校验错误拦截！
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("my_tender_doc.pdf", b"fake binary content", "application/pdf")}
        # 传入全空格和空串打转测试参数拦截弹性
        data = {"source_doc_id": "   "}
        
        resp = await ac.post("/api/v1/bid-scorer/upload-bid", files=files, data=data)

    assert resp.status_code == 400
    assert "缺少关联的招标文件 ID" in resp.json()["detail"]
