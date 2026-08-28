"""make main AwardWallet sections the only buy-points inventory

Revision ID: 0015_simple_buy_points
Revises: 0014_simple_highlights
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_simple_buy_points"
down_revision = "0014_simple_highlights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    offers = sa.table(
        "buy_points_offers",
        sa.column("id", sa.Uuid()),
        sa.column("evidence", sa.JSON()),
    )
    for row in connection.execute(sa.select(offers.c.id, offers.c.evidence)):
        evidence = dict(row.evidence) if isinstance(row.evidence, dict) else {}
        changed = False
        for key in ("top_program_text", "purchase_rate_text"):
            if key in evidence:
                evidence.pop(key)
                changed = True
        if changed:
            connection.execute(
                offers.update().where(offers.c.id == row.id).values(evidence=evidence)
            )

    with op.batch_alter_table("buy_points_snapshots") as batch_op:
        batch_op.drop_column("advertised_offer_count")
    with op.batch_alter_table("buy_points_offers") as batch_op:
        batch_op.drop_column("purchase_rate_raw")
        batch_op.drop_column("purchase_rate_cents")
        batch_op.drop_column("top_pick")


def downgrade() -> None:
    with op.batch_alter_table("buy_points_offers") as batch_op:
        batch_op.add_column(
            sa.Column(
                "top_pick",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "purchase_rate_cents",
                sa.Numeric(precision=10, scale=4),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("purchase_rate_raw", sa.String(length=200), nullable=True)
        )
    with op.batch_alter_table("buy_points_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column("advertised_offer_count", sa.Integer(), nullable=True)
        )

    # Removed recommendation-derived values cannot be reconstructed reliably.
