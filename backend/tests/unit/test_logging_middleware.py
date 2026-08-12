"""
单元测试：中间件日志级别分级测试 (test_logging_middleware.py)

测试说明：
验证 LoggingMiddleware 是否根据 HTTP 响应状态码正确区分日志输出级别：
1. 2xx / 3xx 正常状态码 -> logger.info
2. 4xx 客户端/业务未找到状态码 (如 404) -> logger.warning (避免正常 404 误报错误日志)
3. 5xx 服务器崩溃/内部错误 -> logger.error
"""

import pytest
import httpx
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from app.middleware.logging_middleware import LoggingMiddleware


@pytest.fixture
def test_app():
    """创建挂载 LoggingMiddleware 的测试用 FastAPI 实例"""
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/test-200")
    async def route_200():
        return {"message": "ok"}

    @app.get("/test-404")
    async def route_404():
        raise HTTPException(status_code=404, detail="暂无打分记录")

    @app.get("/test-500")
    async def route_500():
        raise HTTPException(status_code=500, detail="内部服务故障")

    return app


@pytest.mark.asyncio
async def test_logging_middleware_200_status_should_log_info(test_app):
    """
    正常场景测试：HTTP 200 请求完成时，中间件应调用 logger.info 输出正常请求结束日志。
    """
    with patch("app.middleware.logging_middleware.logger.info") as mock_info:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/test-200")

        assert resp.status_code == 200
        assert mock_info.called
        log_str = mock_info.call_args_list[-1][0][0]
        assert "Status: 200" in log_str


@pytest.mark.asyncio
async def test_logging_middleware_404_status_should_log_warning(test_app):
    """
    业务未找到/客户端异常场景测试：HTTP 404 请求完成时，中间件应调用 logger.warning 而非 logger.error，
    确保如 /results/{document_id}/latest 查询无打分记录时不会向控制台错报 error。
    """
    with patch("app.middleware.logging_middleware.logger.warning") as mock_warning, \
         patch("app.middleware.logging_middleware.logger.error") as mock_error:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/test-404")

        assert resp.status_code == 404
        assert mock_warning.called
        assert not mock_error.called
        log_str = mock_warning.call_args_list[-1][0][0]
        assert "Status: 404" in log_str


@pytest.mark.asyncio
async def test_logging_middleware_500_status_should_log_error(test_app):
    """
    服务器崩溃场景测试：HTTP 500 请求完成时，中间件应精准调用 logger.error 输出服务异常错误日志。
    """
    with patch("app.middleware.logging_middleware.logger.error") as mock_error:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/test-500")

        assert resp.status_code == 500
        assert mock_error.called
        log_str = mock_error.call_args_list[-1][0][0]
        assert "Status: 500" in log_str
