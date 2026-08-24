"""add StatusMatch project workflow change sets

Revision ID: 0007_statusmatch_project
Revises: 0006_statusmatch_monitoring
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_statusmatch_project"
down_revision = "0006_statusmatch_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statusmatch_change_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("from_fact_set_id", sa.Uuid(), nullable=True),
        sa.Column("to_fact_set_id", sa.Uuid(), nullable=False),
        sa.Column("activity_document_version_id", sa.Uuid(), nullable=False),
        sa.Column("faq_document_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["status_events.id"]),
        sa.ForeignKeyConstraint(["from_fact_set_id"], ["fact_sets.id"]),
        sa.ForeignKeyConstraint(["to_fact_set_id"], ["fact_sets.id"]),
        sa.ForeignKeyConstraint(
            ["activity_document_version_id"], ["document_versions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["faq_document_version_id"], ["document_versions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "activity_document_version_id",
            "faq_document_version_id",
            name="uq_statusmatch_change_sets_event_snapshot",
        ),
    )
    op.create_index(
        "ix_statusmatch_change_sets_event_created",
        "statusmatch_change_sets",
        ["event_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_statusmatch_change_sets_event_created",
        table_name="statusmatch_change_sets",
    )
    op.drop_table("statusmatch_change_sets")
