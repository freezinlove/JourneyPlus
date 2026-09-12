"""add persistent source discovery cursor

Revision ID: 0012_discovery_cursor
Revises: 0011_mapping_visibility
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_discovery_cursor"
down_revision = "0011_mapping_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_automation_states") as batch_op:
        batch_op.add_column(
            sa.Column("discovery_cursor", sa.String(length=500), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("source_automation_states") as batch_op:
        batch_op.drop_column("discovery_cursor")
