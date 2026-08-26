"""add deterministic buy-points promotion snapshots

Revision ID: 0013_buy_points
Revises: 0012_discovery_cursor
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_buy_points"
down_revision = "0012_discovery_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buy_points_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_item_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("page_title", sa.Text(), nullable=False),
        sa.Column("page_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("advertised_offer_count", sa.Integer(), nullable=True),
        sa.Column("parsed_offer_count", sa.Integer(), nullable=False),
        sa.Column("offers_signature", sa.String(length=64), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "parser_version",
            name="uq_buy_points_snapshot_document_parser",
        ),
    )
    op.create_index(
        "ix_buy_points_snapshots_source_parser_created",
        "buy_points_snapshots",
        ["source_item_id", "parser_version", "created_at"],
        unique=False,
    )
    op.create_table(
        "buy_points_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("offer_key", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("program_name", sa.String(length=500), nullable=False),
        sa.Column("offer_text", sa.Text(), nullable=False),
        sa.Column("offer_kind", sa.String(length=30), nullable=False),
        sa.Column("max_percent", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("purchase_rate_raw", sa.String(length=200), nullable=True),
        sa.Column(
            "purchase_rate_cents",
            sa.Numeric(precision=10, scale=4),
            nullable=True,
        ),
        sa.Column("deadline_raw", sa.String(length=200), nullable=True),
        sa.Column("deadline_date", sa.Date(), nullable=True),
        sa.Column("posting_time_raw", sa.String(length=200), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column("action_url", sa.Text(), nullable=True),
        sa.Column("top_pick", sa.Boolean(), nullable=False),
        sa.Column("material_signature", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["buy_points_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "offer_key", name="uq_buy_points_offer_snapshot_key"
        ),
    )
    op.create_index(
        "ix_buy_points_offers_offer_key_snapshot",
        "buy_points_offers",
        ["offer_key", "snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_buy_points_offers_snapshot",
        "buy_points_offers",
        ["snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_buy_points_offers_snapshot", table_name="buy_points_offers")
    op.drop_index(
        "ix_buy_points_offers_offer_key_snapshot", table_name="buy_points_offers"
    )
    op.drop_table("buy_points_offers")
    op.drop_index(
        "ix_buy_points_snapshots_source_parser_created",
        table_name="buy_points_snapshots",
    )
    op.drop_table("buy_points_snapshots")
