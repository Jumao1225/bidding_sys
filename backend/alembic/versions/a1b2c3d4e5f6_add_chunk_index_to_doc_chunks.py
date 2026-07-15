"""add chunk_index to doc_chunks

Revision ID: a1b2c3d4e5f6
Revises: de28c575af0a
Create Date: 2026-07-14 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9673969f771b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 chunk_index 列，并对已有数据按 (document_id, created_at) 顺序回填。"""
    # 1. 新增列，默认值为 0
    op.add_column('doc_chunks', sa.Column(
        'chunk_index', sa.Integer(), nullable=False, server_default='0',
        comment='文档内切片顺序索引, 从0开始递增'
    ))
    
    # 2. 对已有数据按 document_id 分组、created_at 排序回填 chunk_index
    # 使用 PostgreSQL 窗口函数 ROW_NUMBER() 实现
    op.execute("""
        UPDATE doc_chunks
        SET chunk_index = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY document_id 
                ORDER BY created_at, id
            ) - 1 AS rn
            FROM doc_chunks
        ) AS sub
        WHERE doc_chunks.id = sub.id
    """)
    
    # 3. 移除 server_default（后续由应用层控制）
    op.alter_column('doc_chunks', 'chunk_index', server_default=None)


def downgrade() -> None:
    """移除 chunk_index 列。"""
    op.drop_column('doc_chunks', 'chunk_index')
