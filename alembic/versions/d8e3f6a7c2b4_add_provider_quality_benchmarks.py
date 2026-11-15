"""add provider_quality_benchmarks

Revision ID: d8e3f6a7c2b4
Revises: c7d2e8f4a9b1
Create Date: 2026-11-15 01:40:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = 'd8e3f6a7c2b4'
down_revision: str | None = 'c7d2e8f4a9b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'provider_quality_benchmarks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('provider_product_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('benchmark_version', sa.String(length=16), nullable=False),
        sa.Column('tasks', JSONB(), nullable=False),
        sa.Column('languages', JSONB(), nullable=False),
        sa.Column('score_json', JSONB(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['provider_product_id'], ['provider_products.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_pqb_product_evaluated',
        'provider_quality_benchmarks',
        ['provider_product_id', 'evaluated_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_pqb_product_evaluated', table_name='provider_quality_benchmarks')
    op.drop_table('provider_quality_benchmarks')
