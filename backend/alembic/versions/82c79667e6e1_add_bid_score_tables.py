"""add_bid_score_tables

Revision ID: 82c79667e6e1
Revises: f9b8a7c6d5e4
Create Date: 2026-07-29 13:56:07.117833

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '82c79667e6e1'
down_revision: Union[str, Sequence[str], None] = 'f9b8a7c6d5e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建 bid_score_results 表（打分会话）
    op.create_table('bid_score_results',
    sa.Column('document_id', sa.String(length=36), nullable=False, comment='被评分的投标文件 Document ID'),
    sa.Column('source_doc_id', sa.String(length=36), nullable=False, comment='评分维度来源的招标文件 Document ID'),
    sa.Column('evaluation_method', sa.String(length=255), nullable=True, comment='评标方法（如：综合评分法）'),
    sa.Column('total_score', sa.Float(), nullable=False, comment='AI 给出的总分'),
    sa.Column('max_possible', sa.Float(), nullable=False, comment='满分值'),
    sa.Column('score_rate', sa.Float(), nullable=False, comment='得分率 (total_score / max_possible)'),
    sa.Column('category_scores', sa.JSON(), nullable=True, comment='按大类聚合的分数 JSON'),
    sa.Column('summary', sa.Text(), nullable=True, comment='LLM 生成的总体评价摘要'),
    sa.Column('top_improvements', sa.JSON(), nullable=True, comment='优先级排序的改进建议列表'),
    sa.Column('validation_warnings', sa.JSON(), nullable=True, comment='数学校验告警列表'),
    sa.Column('scoring_rounds', sa.Integer(), nullable=False, comment='共识轮数（默认 3）'),
    sa.Column('model_name', sa.String(length=255), nullable=True, comment='使用的 LLM 模型名称'),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False, comment='租户ID, 多租户SaaS核心隔离字段'),
    sa.Column('user_id', sa.String(length=36), nullable=True, comment='数据创建者用户ID'),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_doc_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bid_score_results_document_id'), 'bid_score_results', ['document_id'], unique=False)
    op.create_index(op.f('ix_bid_score_results_source_doc_id'), 'bid_score_results', ['source_doc_id'], unique=False)
    op.create_index(op.f('ix_bid_score_results_tenant_id'), 'bid_score_results', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_bid_score_results_user_id'), 'bid_score_results', ['user_id'], unique=False)

    # 创建 bid_score_items 表（逐项明细）
    op.create_table('bid_score_items',
    sa.Column('score_result_id', sa.String(length=36), nullable=False, comment='关联的打分会话 ID'),
    sa.Column('item_code', sa.String(length=100), nullable=True, comment="评分项编号（如 '1.1'、'技术三'）"),
    sa.Column('category', sa.String(length=100), nullable=False, comment='一级分类（如：技术分/商务分/价格分）'),
    sa.Column('sub_category', sa.String(length=100), nullable=True, comment='二级分类（如：施工方案/团队配置）'),
    sa.Column('title', sa.String(length=500), nullable=False, comment='评分项名称'),
    sa.Column('max_score', sa.Float(), nullable=False, comment='该项满分'),
    sa.Column('ai_score', sa.Float(), nullable=False, comment='AI 打分（三轮中位数）'),
    sa.Column('confidence', sa.Float(), nullable=False, comment='置信度（三轮一致性 0.0~1.0）'),
    sa.Column('score_variance', sa.Float(), nullable=False, comment='三轮分数标准差'),
    sa.Column('all_round_scores', sa.JSON(), nullable=True, comment='三轮原始分数 [round1, round2, round3]'),
    sa.Column('scoring_basis', sa.Text(), nullable=True, comment='评分依据（引用投标文件原文）'),
    sa.Column('deduction_reason', sa.Text(), nullable=True, comment='扣分原因'),
    sa.Column('suggestion', sa.Text(), nullable=True, comment='该项的改进建议'),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False, comment='租户ID, 多租户SaaS核心隔离字段'),
    sa.Column('user_id', sa.String(length=36), nullable=True, comment='数据创建者用户ID'),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['score_result_id'], ['bid_score_results.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bid_score_items_score_result_id'), 'bid_score_items', ['score_result_id'], unique=False)
    op.create_index(op.f('ix_bid_score_items_tenant_id'), 'bid_score_items', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_bid_score_items_user_id'), 'bid_score_items', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_bid_score_items_user_id'), table_name='bid_score_items')
    op.drop_index(op.f('ix_bid_score_items_tenant_id'), table_name='bid_score_items')
    op.drop_index(op.f('ix_bid_score_items_score_result_id'), table_name='bid_score_items')
    op.drop_table('bid_score_items')
    op.drop_index(op.f('ix_bid_score_results_user_id'), table_name='bid_score_results')
    op.drop_index(op.f('ix_bid_score_results_tenant_id'), table_name='bid_score_results')
    op.drop_index(op.f('ix_bid_score_results_source_doc_id'), table_name='bid_score_results')
    op.drop_index(op.f('ix_bid_score_results_document_id'), table_name='bid_score_results')
    op.drop_table('bid_score_results')

