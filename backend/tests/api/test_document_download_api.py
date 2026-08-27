"""
标书文档原文件下载接口自动化测试 (test_document_download_api.py)
覆盖:
- 正常下载招标文件 (PDF/Word)
- 多租户与跨用户权限隔离拦截 (404)
- 数据库无对应记录拦截 (404)
- 磁盘物理文件缺失拦截 (404)
"""

import os
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from app.main import app
from app.db.session import SessionLocal
from app.db.models.user import User, Tenant
from app.db.models.project import Project, Document
from app.core.security import create_access_token


@pytest.fixture
def document_test_env():
    """创建测试用的租户、用户与测试文档"""
    db = SessionLocal()
    tenant_a = None
    tenant_b = None
    user_a = None
    user_b = None
    project_a = None
    doc_a = None
    test_file_path = None

    try:
        # 1. 租户 A 与 用户 A
        tenant_a = Tenant(name="DocDownloadTenantA", is_active=True)
        db.add(tenant_a)
        db.flush()

        user_a = User(
            email="doc_user_a@example.com",
            hashed_password="fakehashedpassword",
            tenant_id=tenant_a.id,
            role="user",
            is_active=True
        )
        db.add(user_a)

        # 2. 租户 B 与 用户 B
        tenant_b = Tenant(name="DocDownloadTenantB", is_active=True)
        db.add(tenant_b)
        db.flush()

        user_b = User(
            email="doc_user_b@example.com",
            hashed_password="fakehashedpassword",
            tenant_id=tenant_b.id,
            role="user",
            is_active=True
        )
        db.add(user_b)
        db.flush()

        # 3. 关联的项目与文档 (归属于租户 A 与 用户 A)
        project_a = Project(name="测试下载工程项目", tenant_id=tenant_a.id, status="created")
        db.add(project_a)
        db.flush()

        # 创建真实的临时文件供测试下载
        backend_base = Path(__file__).resolve().parents[2]
        temp_upload_dir = backend_base / "uploads" / "tenders"
        temp_upload_dir.mkdir(parents=True, exist_ok=True)
        test_file_path = temp_upload_dir / "test_download_tender_sample.pdf"
        test_file_path.write_bytes(b"%PDF-1.4\nTest Original Document Content\n%%EOF")

        doc_a = Document(
            tenant_id=tenant_a.id,
            user_id=user_a.id,
            project_id=project_a.id,
            filename="测试招标文件_原版.pdf",
            file_path=str(test_file_path),
            parse_status="completed",
            parsed_metadata={"doc_type": "tender"}
        )
        db.add(doc_a)
        db.commit()

        token_a = create_access_token(user_a.id)
        token_b = create_access_token(user_b.id)

        yield {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "user_a": user_a,
            "user_b": user_b,
            "doc_a": doc_a,
            "token_a": token_a,
            "token_b": token_b,
            "test_file_path": test_file_path,
        }

    finally:
        # 清理测试数据
        if doc_a:
            db.delete(doc_a)
        if project_a:
            db.delete(project_a)
        if user_a:
            db.delete(user_a)
        if user_b:
            db.delete(user_b)
        if tenant_a:
            db.delete(tenant_a)
        if tenant_b:
            db.delete(tenant_b)
        db.commit()
        db.close()

        # 清理测试磁盘文件
        if test_file_path and test_file_path.exists():
            test_file_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_download_document_success(document_test_env):
    """测试拥有权限的用户成功下载原文件及响应头验证"""
    env = document_test_env
    doc_id = env["doc_a"].id
    token = env["token_a"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/documents/{doc_id}/download",
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4\nTest Original Document Content\n%%EOF"
    content_disp = response.headers.get("content-disposition", "")
    assert "attachment" in content_disp
    assert "filename*=UTF-8''" in content_disp


@pytest.mark.asyncio
async def test_download_document_cross_tenant_isolation_should_return_404(document_test_env):
    """测试跨租户访问他人文档时被多租户隔离拦截 (404)"""
    env = document_test_env
    doc_id = env["doc_a"].id
    token_b = env["token_b"]  # 租户 B 的用户

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/documents/{doc_id}/download",
            headers={"Authorization": f"Bearer {token_b}"}
        )

    assert response.status_code == 404
    data = response.json()
    assert "未找到" in data.get("detail", "") or "无权访问" in data.get("detail", "")


@pytest.mark.asyncio
async def test_download_nonexistent_document_should_return_404(document_test_env):
    """测试下载不存在的 doc_id 返回 404"""
    env = document_test_env
    token = env["token_a"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/documents/non-existent-doc-id-999/download",
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_document_physical_file_missing_should_return_404(document_test_env):
    """测试数据库存在记录但物理磁盘文件缺失时优雅返回 404"""
    env = document_test_env
    doc_id = env["doc_a"].id
    token = env["token_a"]

    # 临时删除磁盘文件
    env["test_file_path"].unlink(missing_ok=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/documents/{doc_id}/download",
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404
    data = response.json()
    assert "未在服务器上找到" in data.get("detail", "")
