"""remove opportunity type from status events

Revision ID: 0002_remove_opportunity_type
Revises: 0001_status_opportunity_v1
Create Date: 2026-08-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_remove_opportunity_type"
down_revision = "0001_status_opportunity_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("status_events", "opportunity_type")


def downgrade() -> None:
    op.add_column(
        "status_events",
        sa.Column(
            "opportunity_type",
            sa.String(length=100),
            nullable=False,
            server_default="OTHER_DIRECT_STATUS",
        ),
    )
    with op.batch_alter_table("status_events") as batch_op:
        batch_op.alter_column(
            "opportunity_type",
            existing_type=sa.String(length=100),
            existing_nullable=False,
            server_default=None,
        )
