"""add notification_outbox

Revision ID: c7d2e8f4a9b1
Revises: b3f1a9c2d4e5
Create Date: 2026-11-15 00:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = 'c7d2e8f4a9b1'
down_revision: str | None = 'b3f1a9c2d4e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'notification_outbox',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('recipient', sa.Text(), nullable=False),
        sa.Column('template_key', sa.String(length=64), nullable=False),
        sa.Column('language', sa.String(length=8), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=False),
        sa.Column('provider_message_id', sa.String(length=64), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('classification', sa.String(length=32), nullable=False),
        sa.Column('approval_request_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_notification_outbox_status',
        'notification_outbox',
        ['status', 'next_attempt_at'],
    )
    op.create_index(
        'uq_notification_outbox_idem',
        'notification_outbox',
        ['idempotency_key'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_notification_outbox_idem', table_name='notification_outbox')
    op.drop_index('ix_notification_outbox_status', table_name='notification_outbox')
    op.drop_table('notification_outbox')
