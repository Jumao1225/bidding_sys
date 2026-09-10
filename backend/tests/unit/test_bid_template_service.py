"""外部投标模板服务单元测试。"""

import io
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from docx import Document
from fastapi import UploadFile

from app.db.models.bid_template import BidTemplate, BidTemplateBinding
from app.services.bid_template_service import BidTemplateService


def _valid_docx_bytes() -> bytes:
    """构造可解析的最小 DOCX 模板。"""
    document = Document()
    document.add_paragraph("投标文件格式模板")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _query_result(first_result):
    """构造可配置 first() 结果的数据库查询替身。"""
    query = MagicMock()
    query.filter.return_value.first.return_value = first_result
    return query


def test_upload_template_should_validate_save_and_persist_docx(monkeypatch) -> None:
    """正常上传应校验 DOCX、保存文件并创建租户模板记录。"""
    service = BidTemplateService()
    test_root = Path("output") / f"test_bid_template_service_{uuid.uuid4().hex}"
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        BidTemplateService,
        "_get_template_root",
        staticmethod(lambda tenant_id: str(test_root / tenant_id)),
    )
    db = MagicMock()
    db.query.return_value = _query_result(None)
    file = UploadFile(
        filename="空白投标模板.docx",
        file=io.BytesIO(_valid_docx_bytes()),
    )

    try:
        template = service.upload_template(db, file, "tenant-1", "user-1")

        assert isinstance(template, BidTemplate)
        assert template.filename == "空白投标模板.docx"
        assert template.tenant_id == "tenant-1"
        assert template.file_size > 0
        assert Path(template.file_path).is_file()
        db.add.assert_called_once_with(template)
        db.commit.assert_called_once()
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_upload_template_should_reject_non_docx_before_database_write() -> None:
    """非 DOCX 文件应在进入数据库前被拒绝。"""
    service = BidTemplateService()
    db = MagicMock()
    file = UploadFile(filename="模板.pdf", file=io.BytesIO(b"not-docx"))

    with pytest.raises(ValueError, match="仅支持上传"):
        service.upload_template(db, file, "tenant-1", "user-1")

    db.add.assert_not_called()


def test_upload_template_should_reuse_same_sha256_record(monkeypatch) -> None:
    """同一租户重复上传相同内容时应复用已有记录，避免重复文件。"""
    service = BidTemplateService()
    test_root = Path("output") / f"test_bid_template_service_{uuid.uuid4().hex}"
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        BidTemplateService,
        "_get_template_root",
        staticmethod(lambda tenant_id: str(test_root / tenant_id)),
    )
    existing = SimpleNamespace(id="template-existing")
    db = MagicMock()
    db.query.return_value = _query_result(existing)
    file = UploadFile(filename="重复模板.docx", file=io.BytesIO(_valid_docx_bytes()))

    try:
        result = service.upload_template(db, file, "tenant-1", "user-1")

        assert result is existing
        db.add.assert_not_called()
        db.commit.assert_not_called()
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_bind_template_should_update_document_binding_for_same_tenant() -> None:
    """正常绑定应同时校验文档、模板租户，并保存文档到模板的关系。"""
    test_root = Path("output") / f"test_bid_template_service_{uuid.uuid4().hex}"
    test_root.mkdir(parents=True, exist_ok=True)
    template_path = test_root / "template.docx"
    template_path.write_bytes(_valid_docx_bytes())
    document = SimpleNamespace(id="document-1", tenant_id="tenant-1", user_id=None)
    template = SimpleNamespace(id="template-1", tenant_id="tenant-1", file_path=str(template_path))
    db = MagicMock()
    db.query.side_effect = [
        _query_result(document),
        _query_result(template),
        _query_result(None),
    ]

    try:
        binding = BidTemplateService().bind_template(
            db=db,
            document_id="document-1",
            template_id="template-1",
            tenant_id="tenant-1",
            user_id="user-1",
        )

        assert isinstance(binding, BidTemplateBinding)
        assert binding.document_id == "document-1"
        assert binding.template_id == "template-1"
        assert binding.status == "active"
        db.add.assert_called_once_with(binding)
        db.commit.assert_called_once()
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_unbind_template_should_mark_active_binding_inactive() -> None:
    """正常解除绑定应停用关系但保留模板绑定记录。"""
    document = SimpleNamespace(id="document-1", tenant_id="tenant-1", user_id=None)
    binding = SimpleNamespace(document_id="document-1", tenant_id="tenant-1", template_id="template-1", status="active")
    db = MagicMock()
    db.query.side_effect = [
        _query_result(document),
        _query_result(binding),
    ]

    result = BidTemplateService().unbind_template(
        db=db,
        document_id="document-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result is binding
    assert binding.status == "inactive"
    db.commit.assert_called_once()
    db.delete.assert_not_called()


def test_unbind_template_should_be_idempotent_when_no_active_binding() -> None:
    """重复解除或未绑定时应返回空结果且不写数据库。"""
    document = SimpleNamespace(id="document-1", tenant_id="tenant-1", user_id=None)
    db = MagicMock()
    db.query.side_effect = [
        _query_result(document),
        _query_result(None),
    ]

    result = BidTemplateService().unbind_template(
        db=db,
        document_id="document-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result is None
    db.commit.assert_not_called()
