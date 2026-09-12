"""add membership strategy agent state

Revision ID: 0018_membership_agent
Revises: 0017_statusmatch_terms
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_membership_agent"
down_revision = "0017_statusmatch_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("last_response", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_interactions_status_expires",
        "agent_interactions",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_table(
        "agent_wait_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_interaction_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("research_statusmatcher", sa.Boolean(), nullable=False),
        sa.Column("holding_node_ids", sa.JSON(), nullable=False),
        sa.Column("last_candidate_signature", sa.String(length=64), nullable=True),
        sa.Column("pending_result", sa.JSON(), nullable=True),
        sa.Column("pending_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_interaction_id"], ["agent_interactions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_agent_wait_goals_single_active",
        "agent_wait_goals",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_wait_goals_single_active", table_name="agent_wait_goals"
    )
    op.drop_table("agent_wait_goals")
    op.drop_index(
        "ix_agent_interactions_status_expires", table_name="agent_interactions"
    )
    op.drop_table("agent_interactions")
