"""intake external_id idempotency column

Revision ID: b2c9e5d1f8a3
Revises: a1b8d4f0c3e7
Create Date: 2026-11-16
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b2c9e5d1f8a3"
down_revision: str | None = "a1b8d4f0c3e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("intake_messages",
                  sa.Column("external_id", sa.String(255), nullable=True))
    op.create_index("uq_intake_messages_external_id", "intake_messages",
                    ["external_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_intake_messages_external_id", table_name="intake_messages")
    op.drop_column("intake_messages", "external_id")
