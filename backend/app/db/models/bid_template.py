"""投标文件外部模板与招标文档绑定模型。"""

from typing import List

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import TenantBase


class BidTemplate(TenantBase):
    """租户级可复用投标文件空白模板。"""

    __tablename__ = "bid_templates"

    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="用户上传的原始文件名")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="服务器端模板文件路径")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="模板文件 SHA-256")
    file_size: Mapped[int] = mapped_column(nullable=False, comment="模板文件大小，单位字节")
    content_type: Mapped[str | None] = mapped_column(String(150), nullable=True, comment="上传时的 MIME 类型")
    template_type: Mapped[str] = mapped_column(String(50), nullable=False, default="external_docx", comment="模板类型")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, comment="是否允许继续绑定使用")

    bindings: Mapped[List["BidTemplateBinding"]] = relationship(
        "BidTemplateBinding",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "file_sha256", name="uq_bid_template_tenant_sha256"),
    )


class BidTemplateBinding(TenantBase):
    """将一份外部模板绑定到租户内某个招标文档。"""

    __tablename__ = "bid_template_bindings"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True, comment="招标文档 ID"
    )
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bid_templates.id", ondelete="CASCADE"), nullable=False, index=True, comment="模板 ID"
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", comment="绑定状态")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="绑定备注")

    template: Mapped[BidTemplate] = relationship("BidTemplate", back_populates="bindings")

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", name="uq_bid_template_binding_tenant_document"),
    )
