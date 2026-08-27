"""为企业档案表新增 profile_name 和 is_default 字段，支持多主体档案管理。

Revision ID: e2f3a4b5c6d7
Revises: d9e0f1a2b3c4
Create Date: 2026-08-26 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 profile_name 和 is_default 列，并将已有记录标记为默认档案。"""
    op.add_column(
        "company_profiles",
        sa.Column("profile_name", sa.String(length=100), nullable=True, comment="档案显示名称"),
    )
    op.add_column(
        "company_profiles",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否为默认档案",
        ),
    )
    # 将已有的唯一记录标记为默认档案并赋予名称
    op.execute(
        "UPDATE company_profiles SET profile_name = '默认企业档案', is_default = true "
        "WHERE id = (SELECT id FROM company_profiles ORDER BY created_at ASC LIMIT 1)"
    )


def downgrade() -> None:
    """移除 profile_name 和 is_default 列。"""
    op.drop_column("company_profiles", "is_default")
    op.drop_column("company_profiles", "profile_name")
