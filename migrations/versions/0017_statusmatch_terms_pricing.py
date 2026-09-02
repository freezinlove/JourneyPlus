"""add StatusMatch terms document to project snapshots

Revision ID: 0017_statusmatch_terms
Revises: 0016_personalized_match
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_statusmatch_terms"
down_revision = "0016_personalized_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statusmatch_change_sets") as batch_op:
        batch_op.add_column(
            sa.Column("terms_document_version_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_statusmatch_change_sets_terms_document_version_id",
            "document_versions",
            ["terms_document_version_id"],
            ["id"],
        )
        batch_op.drop_constraint(
            "uq_statusmatch_change_sets_event_snapshot_fact",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_statusmatch_change_sets_event_snapshot_fact",
            [
                "event_id",
                "activity_document_version_id",
                "faq_document_version_id",
                "terms_document_version_id",
                "to_fact_set_id",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("statusmatch_change_sets") as batch_op:
        batch_op.drop_constraint(
            "uq_statusmatch_change_sets_event_snapshot_fact",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_statusmatch_change_sets_event_snapshot_fact",
            [
                "event_id",
                "activity_document_version_id",
                "faq_document_version_id",
                "to_fact_set_id",
            ],
        )
        batch_op.drop_constraint(
            "fk_statusmatch_change_sets_terms_document_version_id",
            type_="foreignkey",
        )
        batch_op.drop_column("terms_document_version_id")
