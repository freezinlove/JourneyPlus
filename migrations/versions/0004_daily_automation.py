"""add daily automation state, lease, and run records

Revision ID: 0004_daily_automation
Revises: 0003_status_event_lifecycle
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_daily_automation"
down_revision = "0003_status_event_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_leases",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("day_bucket", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("source_results", sa.JSON(), nullable=False),
        sa.Column("processing_result", sa.JSON(), nullable=False),
        sa.Column("lifecycle_result", sa.JSON(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("backlog_count", sa.Integer(), nullable=False),
        sa.Column("needs_review_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "source_automation_states",
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("last_day_bucket", sa.Date(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_new_document_count", sa.Integer(), nullable=False),
        sa.Column("pending_document_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_table(
        "initialization_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_key", sa.String(length=255), nullable=False),
        sa.Column("batch_type", sa.String(length=50), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("audit_status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("source_results", sa.JSON(), nullable=False),
        sa.Column("processing_result", sa.JSON(), nullable=False),
        sa.Column("audit_notes", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_key"),
    )


def downgrade() -> None:
    op.drop_table("initialization_runs")
    op.drop_table("source_automation_states")
    op.drop_table("automation_runs")
    op.drop_table("automation_leases")
