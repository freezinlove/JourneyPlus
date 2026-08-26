"""add ordinary article mapping visibility lifecycle

Revision ID: 0011_mapping_visibility
Revises: 0010_generic_article_v2
Create Date: 2026-08-25
"""

from __future__ import annotations

from datetime import timedelta

from alembic import op
import sqlalchemy as sa


revision = "0011_mapping_visibility"
down_revision = "0010_generic_article_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("article_opportunities") as batch_op:
        batch_op.add_column(
            sa.Column("visibility_until_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("visibility_policy", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("archive_reason", sa.String(length=40), nullable=True)
        )

    opportunities = sa.table(
        "article_opportunities",
        sa.column("id", sa.Uuid()),
        sa.column("analysis_id", sa.Uuid()),
        sa.column("application_deadline_at", sa.DateTime(timezone=True)),
        sa.column("visibility_until_at", sa.DateTime(timezone=True)),
        sa.column("visibility_policy", sa.String(length=40)),
    )
    analyses = sa.table(
        "article_analyses",
        sa.column("id", sa.Uuid()),
        sa.column("source_item_id", sa.Uuid()),
    )
    source_items = sa.table(
        "source_items",
        sa.column("id", sa.Uuid()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            opportunities.c.id,
            opportunities.c.application_deadline_at,
            source_items.c.published_at,
            source_items.c.created_at,
        )
        .select_from(
            opportunities.join(
                analyses, opportunities.c.analysis_id == analyses.c.id
            ).join(source_items, analyses.c.source_item_id == source_items.c.id)
        )
        .order_by(opportunities.c.id)
    )
    for row in rows:
        if row.application_deadline_at is not None:
            visibility_until_at = row.application_deadline_at
            visibility_policy = "EXPLICIT_DEADLINE"
        else:
            origin = row.published_at or row.created_at
            visibility_until_at = origin + timedelta(days=180)
            visibility_policy = "DEFAULT_180_DAYS"
        connection.execute(
            opportunities.update()
            .where(opportunities.c.id == row.id)
            .values(
                visibility_until_at=visibility_until_at,
                visibility_policy=visibility_policy,
            )
        )

    with op.batch_alter_table("article_opportunities") as batch_op:
        batch_op.alter_column("visibility_until_at", nullable=False)
        batch_op.alter_column("visibility_policy", nullable=False)
        batch_op.create_index(
            "ix_article_opportunities_visibility",
            ["visibility_until_at", "archived_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("article_opportunities") as batch_op:
        batch_op.drop_index("ix_article_opportunities_visibility")
        batch_op.drop_column("archive_reason")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("visibility_policy")
        batch_op.drop_column("visibility_until_at")
