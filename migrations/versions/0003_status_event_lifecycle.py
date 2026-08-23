"""add status event application window and lifecycle

Revision ID: 0003_status_event_lifecycle
Revises: 0002_remove_opportunity_type
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_status_event_lifecycle"
down_revision = "0002_remove_opportunity_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "status_events",
        sa.Column("application_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "status_events",
        sa.Column("application_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "status_events",
        sa.Column(
            "lifecycle_status",
            sa.String(length=30),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "status_events",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_status_events_lifecycle_archived",
        "status_events",
        ["lifecycle_status", "archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_status_events_lifecycle_archived", table_name="status_events"
    )
    op.drop_column("status_events", "archived_at")
    op.drop_column("status_events", "lifecycle_status")
    op.drop_column("status_events", "application_deadline_at")
    op.drop_column("status_events", "application_start_at")
