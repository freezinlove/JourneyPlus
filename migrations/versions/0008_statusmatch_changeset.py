"""version StatusMatch change sets by resulting FactSet

Revision ID: 0008_statusmatch_changeset
Revises: 0007_statusmatch_project
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op


revision = "0008_statusmatch_changeset"
down_revision = "0007_statusmatch_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statusmatch_change_sets") as batch_op:
        batch_op.drop_constraint(
            "uq_statusmatch_change_sets_event_snapshot",
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


def downgrade() -> None:
    with op.batch_alter_table("statusmatch_change_sets") as batch_op:
        batch_op.drop_constraint(
            "uq_statusmatch_change_sets_event_snapshot_fact",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_statusmatch_change_sets_event_snapshot",
            [
                "event_id",
                "activity_document_version_id",
                "faq_document_version_id",
            ],
        )
