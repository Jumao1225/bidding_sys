import pytest
import httpx
from app.main import app

@pytest.mark.asyncio
async def test_health_check():
    """测试探针接口是否存活"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}
