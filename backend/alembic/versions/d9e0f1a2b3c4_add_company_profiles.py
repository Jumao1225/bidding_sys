"""创建企业基础档案表。

Revision ID: d9e0f1a2b3c4
Revises: c7d8e9f0a1b2
Create Date: 2026-08-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建企业基础档案表。"""
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("legal_representative", sa.String(length=100), nullable=True),
        sa.Column("authorized_delegate", sa.String(length=100), nullable=True),
        sa.Column("credit_code", sa.String(length=100), nullable=True),
        sa.Column("registered_address", sa.String(length=500), nullable=True),
        sa.Column("contact_phone", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=100), nullable=True),
        sa.Column("bank_name", sa.String(length=255), nullable=True),
        sa.Column("bank_account", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """删除企业基础档案表。"""
    op.drop_table("company_profiles")
