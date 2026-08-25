"""add third-party StatusMatch article routes and supplements

Revision ID: 0009_statusmatch_articles
Revises: 0008_statusmatch_changeset
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_statusmatch_articles"
down_revision = "0008_statusmatch_changeset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statusmatch_article_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("project_host", sa.String(length=255), nullable=False),
        sa.Column("project_url", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["status_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "project_host",
            name="uq_statusmatch_article_route_document_host",
        ),
    )
    op.create_index(
        "ix_statusmatch_article_routes_event_status",
        "statusmatch_article_routes",
        ["event_id", "status"],
        unique=False,
    )
    op.create_table(
        "statusmatch_article_supplements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("article_document_version_id", sa.Uuid(), nullable=False),
        sa.Column("fact_set_id", sa.Uuid(), nullable=False),
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("input_version", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("highlights", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"], ["statusmatch_article_routes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["status_events.id"]),
        sa.ForeignKeyConstraint(
            ["article_document_version_id"], ["document_versions.id"]
        ),
        sa.ForeignKeyConstraint(["fact_set_id"], ["fact_sets.id"]),
        sa.ForeignKeyConstraint(["brief_id"], ["briefs.id"]),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "fact_set_id",
            "brief_id",
            "input_version",
            name="uq_statusmatch_article_supplement_input",
        ),
    )
    op.create_index(
        "ix_statusmatch_article_supplements_event_fact",
        "statusmatch_article_supplements",
        ["event_id", "fact_set_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_statusmatch_article_supplements_event_fact",
        table_name="statusmatch_article_supplements",
    )
    op.drop_table("statusmatch_article_supplements")
    op.drop_index(
        "ix_statusmatch_article_routes_event_status",
        table_name="statusmatch_article_routes",
    )
    op.drop_table("statusmatch_article_routes")
