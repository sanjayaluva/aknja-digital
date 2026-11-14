"""add llm_call_logs

Revision ID: b3f1a9c2d4e5
Revises: 6e68e69242c8
Create Date: 2026-11-14 23:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3f1a9c2d4e5'
down_revision: Union[str, None] = '6e68e69242c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_call_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('task', sa.String(length=32), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('prompt_hash', sa.String(length=64), nullable=False),
        sa.Column('template_version', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_llm_call_logs_tenant_id_tenants')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_call_logs')),
    )
    op.create_index('ix_llm_call_logs_tenant_created', 'llm_call_logs', ['tenant_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_llm_call_logs_tenant_created', table_name='llm_call_logs')
    op.drop_table('llm_call_logs')
