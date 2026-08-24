"""extend cost_estimates with the complete frontend BOM form fields

Revision ID: c7d8e9f0a1b2
Revises: f9b8a7c6d5e4
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "82c79667e6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = [
        sa.Column("item_code", sa.String(length=100), nullable=True, comment="前端 BOM 项目编码"),
        sa.Column("model", sa.String(length=255), nullable=True, comment="前端 BOM 型号"),
        sa.Column("spec_requirement", sa.Text(), nullable=True, comment="招标文件规格要求原文"),
        sa.Column("matched_name", sa.String(length=255), nullable=True, comment="价格库匹配名称"),
        sa.Column("matched_brand", sa.String(length=255), nullable=True, comment="价格库匹配品牌"),
        sa.Column("matched_model", sa.String(length=255), nullable=True, comment="价格库匹配型号"),
        sa.Column("matched_manufacturer", sa.String(length=255), nullable=True, comment="价格库匹配生产厂家"),
        sa.Column("key_parameters", sa.JSON(), nullable=True, comment="关键参数"),
        sa.Column("brand_requirements", sa.Text(), nullable=True, comment="招标文件品牌/产地要求"),
        sa.Column("match_quality", sa.String(length=50), nullable=True, comment="匹配质量"),
        sa.Column("warning", sa.Text(), nullable=True, comment="价格匹配预警"),
        sa.Column("comparison_note", sa.Text(), nullable=True, comment="价格对比说明"),
        sa.Column("parent_item", sa.String(length=255), nullable=True, comment="直接父级设备"),
        sa.Column("root_item", sa.String(length=255), nullable=True, comment="顶层标的物"),
        sa.Column("tree_level", sa.Integer(), nullable=True, comment="BOM 层级"),
        sa.Column("per_set_qty", sa.Float(), nullable=True, comment="单套定额数量"),
        sa.Column("per_set_quantity", sa.Float(), nullable=True, comment="单套定额数量兼容字段"),
        sa.Column("sort_order", sa.Integer(), nullable=True, comment="前端 BOM 原始顺序"),
    ]
    for column in columns:
        op.add_column("cost_estimates", column)
    op.create_index("ix_cost_estimates_sort_order", "cost_estimates", ["sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cost_estimates_sort_order", table_name="cost_estimates")
    for name in [
        "sort_order", "per_set_quantity", "per_set_qty", "tree_level", "root_item", "parent_item",
        "comparison_note", "warning", "match_quality", "brand_requirements", "key_parameters",
        "matched_manufacturer", "matched_model", "matched_brand", "matched_name", "spec_requirement",
        "model", "item_code",
    ]:
        op.drop_column("cost_estimates", name)
