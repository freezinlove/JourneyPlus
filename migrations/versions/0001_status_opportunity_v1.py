"""Create the status opportunity V1 data model."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_status_opportunity_v1"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("adapter_type", sa.String(100), nullable=False),
        sa.Column("discovery_config", sa.JSON(), nullable=False),
        sa.Column("access_policy", sa.JSON(), nullable=False),
        sa.Column("collection_cadence", sa.String(100), nullable=True),
        sa.Column("automatic_scheduling", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_table(
        "source_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovery_fingerprint", sa.String(128)),
        sa.Column("raw_metadata", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index("ix_source_items_canonical_url", "source_items", ["canonical_url"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_item_id", sa.Uuid(), sa.ForeignKey("source_items.id"), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("raw_body", sa.Text()),
        sa.Column("normalized_body", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("storage_mode", sa.String(100), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duplicate_of_id", sa.Uuid(), sa.ForeignKey("document_versions.id")),
        *timestamps(),
        sa.UniqueConstraint("source_item_id", "raw_hash"),
    )
    op.create_index(
        "ix_document_versions_normalized_hash",
        "document_versions",
        ["normalized_hash"],
    )
    op.create_table(
        "status_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_from_key", sa.String(255), nullable=False, unique=True),
        sa.Column("program", sa.String(300), nullable=False),
        sa.Column("opportunity_type", sa.String(100), nullable=False),
        sa.Column("target_status", sa.String(300)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("merged_into_id", sa.Uuid(), sa.ForeignKey("status_events.id")),
        sa.Column("current_fact_set_id", sa.Uuid()),
        sa.Column("current_brief_id", sa.Uuid()),
        *timestamps(),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id")),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("status_events.id")),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_version", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("model_config_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        *timestamps(),
    )
    op.create_table(
        "event_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("status_events.id"), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("relationship", sa.String(50), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("event_id", "document_version_id", "relationship"),
    )
    op.create_table(
        "event_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("status_events.id"), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("hint_index", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("event_id", "document_version_id", "hint_index"),
    )
    op.create_table(
        "fact_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("status_events.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("has_conflicts", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("event_id", "version"),
    )
    op.create_table(
        "briefs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fact_set_id", sa.Uuid(), sa.ForeignKey("fact_sets.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("fact_set_id", "version"),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("target_entity_id", sa.Uuid()),
        sa.Column("reason", sa.Text()),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "gold_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_text", sa.Text(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("case_id", "version"),
    )


def downgrade() -> None:
    for table in (
        "gold_cases",
        "review_decisions",
        "briefs",
        "fact_sets",
        "event_evidence",
        "event_revisions",
        "analysis_runs",
        "status_events",
        "document_versions",
        "source_items",
        "job_runs",
        "collection_runs",
        "sources",
    ):
        op.drop_table(table)

