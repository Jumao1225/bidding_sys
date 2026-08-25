"""Add tenant model configs.

Revision ID: f1a2b3c4d5e6
Revises: d9e0f1a2b3c4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建租户级模型配置表。"""
    op.create_table(
        "tenant_model_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("OPENAI_API_KEY", sa.String(length=2048), nullable=False),
        sa.Column("OPENAI_API_BASE", sa.String(length=1024), nullable=False),
        sa.Column("LLM_MODEL_NAME", sa.String(length=255), nullable=False),
        sa.Column("MINERU_API_TOKEN", sa.String(length=2048), nullable=False),
        sa.Column("MINERU_API_BASE_URL", sa.String(length=1024), nullable=False),
        sa.Column("ALI_VLM_API_KEY", sa.String(length=2048), nullable=False),
        sa.Column("ALI_VLM_API_BASE", sa.String(length=1024), nullable=False),
        sa.Column("ALI_VLM_MODEL_NAME", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )


def downgrade() -> None:
    """删除租户级模型配置表。"""
    op.drop_table("tenant_model_configs")
