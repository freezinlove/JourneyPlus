"""add generic article V2 records and third-party mapping claims

Revision ID: 0010_generic_article_v2
Revises: 0009_statusmatch_articles
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_generic_article_v2"
down_revision = "0009_statusmatch_articles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_item_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("input_version", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("content_signature", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id"),
    )
    op.create_index(
        "ix_article_analyses_source_item_created",
        "article_analyses",
        ["source_item_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "article_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_index", sa.Integer(), nullable=False),
        sa.Column("program", sa.String(length=300), nullable=False),
        sa.Column("target_status", sa.String(length=300), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("application_start_raw", sa.Text(), nullable=True),
        sa.Column("application_deadline_raw", sa.Text(), nullable=True),
        sa.Column("application_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False),
        sa.Column("action_links", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("fact_signature", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_brief_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["article_analyses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "opportunity_index", name="uq_article_opportunity_index"
        ),
    )
    op.create_index(
        "ix_article_opportunities_analysis_status",
        "article_opportunities",
        ["analysis_id", "status"],
        unique=False,
    )
    op.create_table(
        "article_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("input_version", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["article_opportunities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_id", "version"),
        sa.UniqueConstraint(
            "opportunity_id", "input_version", name="uq_article_brief_input"
        ),
    )
    with op.batch_alter_table("statusmatch_article_supplements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mapping_claims",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("statusmatch_article_supplements") as batch_op:
        batch_op.drop_column("mapping_claims")
    op.drop_table("article_briefs")
    op.drop_index(
        "ix_article_opportunities_analysis_status", table_name="article_opportunities"
    )
    op.drop_table("article_opportunities")
    op.drop_index(
        "ix_article_analyses_source_item_created", table_name="article_analyses"
    )
    op.drop_table("article_analyses")
