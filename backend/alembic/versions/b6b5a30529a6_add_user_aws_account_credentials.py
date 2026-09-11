"""add access_key_id/secret_access_key to user_aws_accounts

Revision ID: b6b5a30529a6
Revises: 1a64baba842b
Create Date: 2026-09-10 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b6b5a30529a6'
down_revision: Union[str, None] = '1a64baba842b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_aws_accounts',
        sa.Column('access_key_id', sa.String(length=128), nullable=False, server_default=''),
    )
    op.add_column(
        'user_aws_accounts',
        sa.Column('secret_access_key', sa.String(length=256), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('user_aws_accounts', 'secret_access_key')
    op.drop_column('user_aws_accounts', 'access_key_id')
