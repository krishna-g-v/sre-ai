"""add converted_to_markdown to kb.documents

Revision ID: 90fe21219dc8
Revises: b6b5a30529a6
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '90fe21219dc8'
down_revision: Union[str, None] = 'b6b5a30529a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('converted_to_markdown', sa.Boolean(), nullable=False, server_default=sa.false()),
        schema='kb',
    )


def downgrade() -> None:
    op.drop_column('documents', 'converted_to_markdown', schema='kb')
