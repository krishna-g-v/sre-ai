"""add user_aws_accounts

Revision ID: 1a64baba842b
Revises: 6e11010967fb
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1a64baba842b'
down_revision: Union[str, None] = '6e11010967fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_aws_accounts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('account_id', sa.String(length=20), nullable=False),
        sa.Column('role_arn', sa.String(length=500), nullable=False),
        sa.Column('external_id', sa.String(length=200), nullable=False),
        sa.Column('region', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'label', name='uq_user_aws_accounts_user_label'),
    )


def downgrade() -> None:
    op.drop_table('user_aws_accounts')
