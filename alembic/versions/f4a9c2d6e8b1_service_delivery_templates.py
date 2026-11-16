"""service delivery: templates, project link, ai tasks, inline artifacts

Revision ID: f4a9c2d6e8b1
Revises: e5f7a1b3c9d2
Create Date: 2026-11-16 00:00:00.000000

Enables the catalog -> delivery flow (T-026):
  services.delivery_template  per-service milestone/task blueprint (JSONB)
  projects.service_id         the catalog service item this project delivers
  tasks.ai_task               the governed AI task profile a task can run
  artifacts.content           inline content for AI-generated artifacts
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = 'f4a9c2d6e8b1'
down_revision: str | None = 'e5f7a1b3c9d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('services', sa.Column('delivery_template', JSONB, nullable=True))
    op.add_column('projects', sa.Column('service_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_projects_service_id', 'projects', 'services', ['service_id'], ['id'],
        ondelete='SET NULL',
    )
    op.add_column('tasks', sa.Column('ai_task', sa.String(32), nullable=True))
    op.add_column('artifacts', sa.Column('content', sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column('artifacts', 'content')
    op.drop_column('tasks', 'ai_task')
    op.drop_constraint('fk_projects_service_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'service_id')
    op.drop_column('services', 'delivery_template')
