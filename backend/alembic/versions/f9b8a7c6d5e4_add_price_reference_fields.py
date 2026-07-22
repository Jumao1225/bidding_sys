"""add brand spec model manufacturer remark to market_price_references

Revision ID: f9b8a7c6d5e4
Revises: 87e7cf35c010
Create Date: 2026-07-22 08:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f9b8a7c6d5e4'
down_revision: Union[str, Sequence[str], None] = '87e7cf35c010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('market_price_references', sa.Column('brand', sa.String(length=100), nullable=True, comment='品牌'))
    op.add_column('market_price_references', sa.Column('spec', sa.String(length=255), nullable=True, comment='规格'))
    op.add_column('market_price_references', sa.Column('model', sa.String(length=100), nullable=True, comment='型号'))
    op.add_column('market_price_references', sa.Column('manufacturer', sa.String(length=255), nullable=True, comment='生产厂商'))
    op.add_column('market_price_references', sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'))


def downgrade() -> None:
    op.drop_column('market_price_references', 'remark')
    op.drop_column('market_price_references', 'manufacturer')
    op.drop_column('market_price_references', 'model')
    op.drop_column('market_price_references', 'spec')
    op.drop_column('market_price_references', 'brand')
