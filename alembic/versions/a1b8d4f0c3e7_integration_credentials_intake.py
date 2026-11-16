"""integration credentials, intake messages, provider product model

Revision ID: a1b8d4f0c3e7
Revises: f4a9c2d6e8b1
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "a1b8d4f0c3e7"
down_revision: str | None = "f4a9c2d6e8b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- credential hub (docs/34 §2.1) ---
    op.create_table(
        "integration_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("payload_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_result", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider_key",
                            name="uq_integration_provider"),
    )
    op.create_index("ix_integration_credentials_tenant",
                    "integration_credentials", ["tenant_id", "status"])

    # --- unified intake (docs/34 §2.3) ---
    op.create_table(
        "intake_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="RECEIVED"),
        sa.Column("ai_classification", JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("ai_extraction", JSONB(), nullable=False, server_default="{}"),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id"),
                  nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_intake_messages_tenant_status",
                    "intake_messages", ["tenant_id", "status"])

    # --- admin-editable model per provider product (docs/34 §2.4) ---
    op.add_column("provider_products",
                  sa.Column("model", sa.String(128), nullable=False,
                            server_default=""))


def downgrade() -> None:
    op.drop_column("provider_products", "model")
    op.drop_index("ix_intake_messages_tenant_status", table_name="intake_messages")
    op.drop_table("intake_messages")
    op.drop_index("ix_integration_credentials_tenant",
                  table_name="integration_credentials")
    op.drop_table("integration_credentials")
