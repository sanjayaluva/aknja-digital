"""add backup offsite columns

Revision ID: e5f7a1b3c9d2
Revises: d8e3f6a7c2b4
Create Date: 2026-11-15 12:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e5f7a1b3c9d2'
down_revision: str | None = 'd8e3f6a7c2b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('backup_records', sa.Column('offsite_key', sa.Text(), nullable=True))
    op.add_column('backup_records', sa.Column('offsite_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('backup_records', 'offsite_at')
    op.drop_column('backup_records', 'offsite_key')
