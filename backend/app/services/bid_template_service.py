"""外部投标 Word 模板上传、租户隔离与招标文档绑定服务。"""

import hashlib
import os
import uuid
import zipfile
from io import BytesIO
from typing import List, Optional

from docx import Document as WordDocument
from fastapi import UploadFile
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.bid_template import BidTemplate, BidTemplateBinding
from app.db.models.project import Document


class BidTemplateService:
    """管理用户提供的空白投标模板，不修改模板正文内容。"""

    allowed_suffix = ".docx"
    max_file_size = 30 * 1024 * 1024

    @staticmethod
    def _get_template_root(tenant_id: str) -> str:
        """返回租户隔离的模板存储目录。"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(backend_root, "uploads", "templates", tenant_id)

    def upload_template(
        self,
        db: Session,
        file: UploadFile,
        tenant_id: str,
        user_id: Optional[str],
    ) -> BidTemplate:
        """校验并保存一份外部 DOCX 空白模板。"""
        original_filename = os.path.basename(file.filename or "").strip()
        if not original_filename or os.path.splitext(original_filename)[1].lower() != self.allowed_suffix:
            raise ValueError("仅支持上传 .docx 格式的 Word 模板")

        try:
            file.file.seek(0)
            file_bytes = file.file.read(self.max_file_size + 1)
        except (OSError, ValueError) as read_error:
            logger.exception("读取投标模板上传内容失败: filename={}, error={}", original_filename, read_error)
            raise ValueError("读取模板文件失败") from read_error

        if len(file_bytes) > self.max_file_size:
            raise ValueError(f"模板文件不能超过 {self.max_file_size // 1024 // 1024} MB")

        self._validate_docx_bytes(file_bytes, original_filename)
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        existing = db.query(BidTemplate).filter(
            BidTemplate.tenant_id == tenant_id,
            BidTemplate.file_sha256 == file_sha256,
        ).first()
        if existing:
            logger.info("命中租户内重复投标模板，复用已有记录: template_id={}, tenant_id={}", existing.id, tenant_id)
            return existing

        template_root = self._get_template_root(tenant_id)
        template_path = os.path.join(template_root, f"{uuid.uuid4()}.docx")
        try:
            os.makedirs(template_root, exist_ok=True)
            with open(template_path, "wb") as template_file:
                template_file.write(file_bytes)

            template = BidTemplate(
                tenant_id=tenant_id,
                user_id=user_id,
                filename=original_filename,
                file_path=template_path,
                file_sha256=file_sha256,
                file_size=len(file_bytes),
                content_type=file.content_type,
                template_type="external_docx",
                is_active=True,
            )
            db.add(template)
            db.commit()
            db.refresh(template)
            logger.info(
                "已保存外部投标模板: template_id={}, tenant_id={}, filename={}, bytes={}",
                template.id,
                tenant_id,
                original_filename,
                len(file_bytes),
            )
            return template
        except (OSError, SQLAlchemyError) as save_error:
            db.rollback()
            self._remove_file_after_failed_save(template_path)
            logger.exception("保存外部投标模板失败: tenant_id={}, filename={}, error={}", tenant_id, original_filename, save_error)
            raise ValueError("保存模板文件失败") from save_error

    @staticmethod
    def _validate_docx_bytes(file_bytes: bytes, filename: str) -> None:
        """通过 Word 解析器验证上传内容确实是可打开的 DOCX。"""
        if not file_bytes:
            raise ValueError("模板文件不能为空")
        try:
            WordDocument(BytesIO(file_bytes))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as validation_error:
            logger.warning("投标模板不是可解析的 DOCX: filename={}, error={}", filename, validation_error)
            raise ValueError("模板文件损坏或不是有效的 DOCX") from validation_error
        except Exception as validation_error:
            logger.exception("解析投标模板时发生未预期异常: filename={}, error={}", filename, validation_error)
            raise ValueError("模板文件损坏或不是有效的 DOCX") from validation_error

    @staticmethod
    def _remove_file_after_failed_save(file_path: str) -> None:
        """数据库保存失败时清理本次新建的孤立文件。"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info("已清理未入库的投标模板文件: {}", file_path)
        except OSError as cleanup_error:
            logger.exception("清理未入库投标模板文件失败: path={}, error={}", file_path, cleanup_error)

    def list_templates(self, db: Session, tenant_id: str) -> List[BidTemplate]:
        """获取当前租户仍可使用的外部模板。"""
        return db.query(BidTemplate).filter(
            BidTemplate.tenant_id == tenant_id,
            BidTemplate.is_active.is_(True),
        ).order_by(BidTemplate.created_at.desc()).all()

    def bind_template(
        self,
        db: Session,
        document_id: str,
        template_id: str,
        tenant_id: str,
        user_id: Optional[str],
        note: Optional[str] = None,
    ) -> BidTemplateBinding:
        """将模板绑定到当前租户内的招标文档，并覆盖该文档旧绑定。"""
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        ).first()
        if not document:
            raise LookupError("招标文档不存在或无权访问")
        if document.user_id and user_id and document.user_id != user_id:
            raise LookupError("招标文档不存在或无权访问")

        template = db.query(BidTemplate).filter(
            BidTemplate.id == template_id,
            BidTemplate.tenant_id == tenant_id,
            BidTemplate.is_active.is_(True),
        ).first()
        if not template:
            raise LookupError("模板不存在、已停用或无权访问")
        if not os.path.isfile(template.file_path):
            logger.error("绑定模板的物理文件不存在: template_id={}, path={}", template_id, template.file_path)
            raise FileNotFoundError("模板文件不存在，请重新上传")

        binding = db.query(BidTemplateBinding).filter(
            BidTemplateBinding.document_id == document_id,
            BidTemplateBinding.tenant_id == tenant_id,
        ).first()
        if binding:
            binding.template_id = template_id
            binding.user_id = user_id
            binding.status = "active"
            binding.note = note
        else:
            binding = BidTemplateBinding(
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                template_id=template_id,
                status="active",
                note=note,
            )
            db.add(binding)

        try:
            db.commit()
            db.refresh(binding)
            logger.info(
                "已绑定投标模板: document_id={}, template_id={}, tenant_id={}",
                document_id,
                template_id,
                tenant_id,
            )
            return binding
        except SQLAlchemyError as bind_error:
            db.rollback()
            logger.exception(
                "绑定投标模板失败: document_id={}, template_id={}, error={}",
                document_id,
                template_id,
                bind_error,
            )
            raise ValueError("绑定模板失败") from bind_error

    def get_template(self, db: Session, template_id: str, tenant_id: str) -> Optional[BidTemplate]:
        """按租户读取可用模板。"""
        return db.query(BidTemplate).filter(
            BidTemplate.id == template_id,
            BidTemplate.tenant_id == tenant_id,
            BidTemplate.is_active.is_(True),
        ).first()

    def unbind_template(
        self,
        db: Session,
        document_id: str,
        tenant_id: str,
        user_id: Optional[str],
    ) -> Optional[BidTemplateBinding]:
        """解除招标文档的当前模板绑定，但保留绑定记录和模板文件。"""
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        ).first()
        if not document:
            raise LookupError("招标文档不存在或无权访问")
        if document.user_id and user_id and document.user_id != user_id:
            raise LookupError("招标文档不存在或无权访问")

        binding = db.query(BidTemplateBinding).filter(
            BidTemplateBinding.document_id == document_id,
            BidTemplateBinding.tenant_id == tenant_id,
            BidTemplateBinding.status == "active",
        ).first()
        if not binding:
            logger.info("解除模板绑定时未找到 active 绑定，按幂等成功处理: document_id={}", document_id)
            return None

        binding.status = "inactive"
        try:
            db.commit()
            db.refresh(binding)
            logger.info(
                "已解除投标模板绑定: document_id={}, template_id={}, tenant_id={}",
                document_id,
                binding.template_id,
                tenant_id,
            )
            return binding
        except SQLAlchemyError as unbind_error:
            db.rollback()
            logger.exception(
                "解除投标模板绑定失败: document_id={}, tenant_id={}, error={}",
                document_id,
                tenant_id,
                unbind_error,
            )
            raise ValueError("解除模板绑定失败") from unbind_error

    def get_bound_template(self, db: Session, document_id: str, tenant_id: str) -> Optional[BidTemplate]:
        """读取招标文档当前生效的外部模板。"""
        return db.query(BidTemplate).join(
            BidTemplateBinding,
            BidTemplateBinding.template_id == BidTemplate.id,
        ).filter(
            BidTemplateBinding.document_id == document_id,
            BidTemplateBinding.tenant_id == tenant_id,
            BidTemplateBinding.status == "active",
            BidTemplate.tenant_id == tenant_id,
            BidTemplate.is_active.is_(True),
        ).first()

    def get_binding(self, db: Session, document_id: str, tenant_id: str) -> Optional[BidTemplateBinding]:
        """读取招标文档当前生效的模板绑定关系。"""
        return db.query(BidTemplateBinding).filter(
            BidTemplateBinding.document_id == document_id,
            BidTemplateBinding.tenant_id == tenant_id,
            BidTemplateBinding.status == "active",
        ).first()


bid_template_service = BidTemplateService()
