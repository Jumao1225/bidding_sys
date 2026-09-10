"""新增外部投标模板及其招标文档绑定表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c5d6e7a8b9"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建租户隔离的模板文件表与文档绑定表。"""
    op.create_table(
        "bid_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="租户ID"),
        sa.Column("user_id", sa.String(length=36), nullable=True, comment="数据创建者用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False, comment="用户上传的原始文件名"),
        sa.Column("file_path", sa.String(length=500), nullable=False, comment="服务器端模板文件路径"),
        sa.Column("file_sha256", sa.String(length=64), nullable=False, comment="模板文件 SHA-256"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="模板文件大小，单位字节"),
        sa.Column("content_type", sa.String(length=150), nullable=True, comment="上传时的 MIME 类型"),
        sa.Column("template_type", sa.String(length=50), nullable=False, server_default="external_docx", comment="模板类型"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否允许继续绑定使用"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "file_sha256", name="uq_bid_template_tenant_sha256"),
    )
    op.create_index("ix_bid_templates_tenant_id", "bid_templates", ["tenant_id"], unique=False)
    op.create_index("ix_bid_templates_file_sha256", "bid_templates", ["file_sha256"], unique=False)

    op.create_table(
        "bid_template_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="租户ID"),
        sa.Column("user_id", sa.String(length=36), nullable=True, comment="数据创建者用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=False, comment="招标文档 ID"),
        sa.Column("template_id", sa.String(length=36), nullable=False, comment="模板 ID"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active", comment="绑定状态"),
        sa.Column("note", sa.Text(), nullable=True, comment="绑定备注"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["bid_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "document_id", name="uq_bid_template_binding_tenant_document"),
    )
    op.create_index("ix_bid_template_bindings_tenant_id", "bid_template_bindings", ["tenant_id"], unique=False)
    op.create_index("ix_bid_template_bindings_document_id", "bid_template_bindings", ["document_id"], unique=False)
    op.create_index("ix_bid_template_bindings_template_id", "bid_template_bindings", ["template_id"], unique=False)


def downgrade() -> None:
    """删除模板绑定表与模板文件表。"""
    op.drop_index("ix_bid_template_bindings_template_id", table_name="bid_template_bindings")
    op.drop_index("ix_bid_template_bindings_document_id", table_name="bid_template_bindings")
    op.drop_index("ix_bid_template_bindings_tenant_id", table_name="bid_template_bindings")
    op.drop_table("bid_template_bindings")
    op.drop_index("ix_bid_templates_file_sha256", table_name="bid_templates")
    op.drop_index("ix_bid_templates_tenant_id", table_name="bid_templates")
    op.drop_table("bid_templates")
