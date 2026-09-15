from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(100), nullable=False)
    discovery_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    access_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    collection_cadence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    automatic_scheduling: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


from journeyplus.user_scope import user_id


class UserBusinessOperation(Base):
    """Rollback journal for explicit holdings and independent waiting state only."""
    __tablename__='user_business_operations'
    user_id: Mapped[UUID] = mapped_column(Uuid, default=user_id, nullable=False, index=True)
    __table_args__=(CheckConstraint("entity_kind IN ('HOLDING','WAIT_GOAL')",name='ck_user_operation_kind'),)
    sequence:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    operation_id:Mapped[UUID]=mapped_column(Uuid,default=uuid4,unique=True,nullable=False)
    entity_kind:Mapped[str]=mapped_column(String(20),nullable=False)
    entity_id:Mapped[UUID]=mapped_column(Uuid,nullable=False)
    before_state:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    after_state:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    payload_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now_utc,nullable=False)


class StatusHolding(Base, TimestampMixin):
    __tablename__ = "status_holdings"
    user_id: Mapped[UUID] = mapped_column(Uuid, default=user_id, nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("user_id", "program_key"),
        ForeignKeyConstraint(["tier_id", "program_id"], ["membership_tiers.id", "membership_tiers.program_id"], name="fk_holding_tier_program"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    program_key: Mapped[str] = mapped_column(String(300), nullable=False)
    tier_key: Mapped[str] = mapped_column(String(300), nullable=False)
    program_display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    tier_display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Nullable during additive backfill; ambiguous legacy identities stay unconfirmed.
    program_id: Mapped[UUID | None] = mapped_column(ForeignKey("membership_programs.id", name="fk_holding_program"))
    tier_id: Mapped[UUID | None] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    identity_status: Mapped[str] = mapped_column(String(30), default="NEEDS_CONFIRMATION", server_default="NEEDS_CONFIRMATION")
    source_record: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}", nullable=False)


class AgentInteraction(Base, TimestampMixin):
    __tablename__ = "agent_interactions"
    user_id: Mapped[UUID] = mapped_column(Uuid, default=user_id, nullable=False, index=True)
    __table_args__ = (Index("ix_agent_interactions_status_expires", "status", "expires_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentWaitGoal(Base, TimestampMixin):
    __tablename__ = "agent_wait_goals"
    __table_args__ = (
        CheckConstraint("singleton_key = 1", name="ck_wait_singleton"),
        Index(
            "uq_agent_wait_goals_single_active",
            "singleton_key",
            unique=True,
            sqlite_where=sql_text("status IN ('ACTIVE','RESULT_PENDING','NEEDS_RECONFIRMATION')"),
            postgresql_where=sql_text("status IN ('ACTIVE','RESULT_PENDING','NEEDS_RECONFIRMATION')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_interaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_interactions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    preferences: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    research_statusmatcher: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    holding_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_candidate_signature: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    seen_candidate_signatures: Mapped[list[str]] = mapped_column(JSON,default=list,server_default='[]',nullable=False)
    pending_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pending_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    singleton_key: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    holding_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    conditions_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    readiness: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}", nullable=False)
    last_checked_snapshot: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[UUID | None] = mapped_column(Uuid)
    result_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CollectionRun(Base, TimestampMixin):
    __tablename__ = "collection_runs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRun(Base, TimestampMixin):
    __tablename__ = "job_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationLease(Base, TimestampMixin):
    __tablename__ = "automation_leases"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationRun(Base, TimestampMixin):
    __tablename__ = "automation_runs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    day_bucket: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    processing_result: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    lifecycle_result: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    model_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backlog_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InitializationRun(Base, TimestampMixin):
    __tablename__ = "initialization_runs"
    __table_args__ = (UniqueConstraint("batch_key"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    batch_key: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_type: Mapped[str] = mapped_column(String(50), nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    audit_status: Mapped[str] = mapped_column(
        String(30), default="PENDING", nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    processing_result: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    audit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceAutomationState(Base, TimestampMixin):
    __tablename__ = "source_automation_states"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id"), primary_key=True
    )
    discovery_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_day_bucket: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_new_document_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    pending_document_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )


class SourceItem(Base, TimestampMixin):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_source_items_canonical_url", "canonical_url"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    discovered_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovery_fingerprint: Mapped[str | None] = mapped_column(String(128))
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    document_role: Mapped[str] = mapped_column(String(30), default="OTHER", server_default="OTHER")


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "source_item_id",
            "raw_hash",
            "parser_version",
            name="uq_document_versions_source_item_raw_parser",
        ),
        Index("ix_document_versions_normalized_hash", "normalized_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_items.id"), nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_body: Mapped[str | None] = mapped_column(Text)
    normalized_body: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_mode: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    section_parser_version: Mapped[str | None] = mapped_column(String(100))


class BuyPointsSnapshotRecord(Base, TimestampMixin):
    """Immutable deterministic parse of one AwardWallet page version."""

    __tablename__ = "buy_points_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "parser_version",
            name="uq_buy_points_snapshot_document_parser",
        ),
        Index(
            "ix_buy_points_snapshots_source_parser_created",
            "source_item_id",
            "parser_version",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_items.id"), nullable=False
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    page_title: Mapped[str] = mapped_column(Text, nullable=False)
    page_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parsed_offer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    offers_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


class BuyPointsOfferRecord(Base, TimestampMixin):
    """One immutable offer row inside a buy-points snapshot."""

    __tablename__ = "buy_points_offers"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "offer_key", name="uq_buy_points_offer_snapshot_key"
        ),
        Index("ix_buy_points_offers_offer_key_snapshot", "offer_key", "snapshot_id"),
        Index("ix_buy_points_offers_snapshot", "snapshot_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("buy_points_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    offer_key: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    program_name: Mapped[str] = mapped_column(String(500), nullable=False)
    offer_text: Mapped[str] = mapped_column(Text, nullable=False)
    offer_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    max_percent: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    deadline_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deadline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    posting_time_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    material_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AnalysisRun(Base, TimestampMixin):
    __tablename__ = "analysis_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("status_events.id"))
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_version: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class ArticleAnalysisRecord(Base, TimestampMixin):
    """Immutable V2 interpretation of one source document version."""

    __tablename__ = "article_analyses"
    __table_args__ = (
        UniqueConstraint("analysis_run_id"),
        Index("ix_article_analyses_source_item_created", "source_item_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    source_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_items.id"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=False
    )
    input_version: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    content_signature: Mapped[str] = mapped_column(String(64), nullable=False)


class ArticleOpportunityRecord(Base, TimestampMixin):
    """One independently readable opportunity extracted from a single article."""

    __tablename__ = "article_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "opportunity_index", name="uq_article_opportunity_index"
        ),
        Index("ix_article_opportunities_analysis_status", "analysis_id", "status"),
        Index(
            "ix_article_opportunities_visibility",
            "visibility_until_at",
            "archived_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_index: Mapped[int] = mapped_column(Integer, nullable=False)
    program: Mapped[str] = mapped_column(String(300), nullable=False)
    target_status: Mapped[str | None] = mapped_column(String(300), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    application_start_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_deadline_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    application_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(30), default="UNKNOWN", nullable=False
    )
    visibility_until_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    visibility_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action_links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fact_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", nullable=False)
    current_brief_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class ArticleBriefRecord(Base, TimestampMixin):
    """Versioned brief generated only from an ArticleOpportunity fact snapshot."""

    __tablename__ = "article_briefs"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version"),
        UniqueConstraint(
            "opportunity_id", "input_version", name="uq_article_brief_input"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_opportunities.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=False
    )
    input_version: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)


class StatusEvent(Base, TimestampMixin):
    __tablename__ = "status_events"
    __table_args__ = (
        Index("ix_status_events_lifecycle_archived", "lifecycle_status", "archived_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    created_from_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    program: Mapped[str] = mapped_column(String(300), nullable=False)
    target_status: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)
    application_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    application_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(30), default="UNKNOWN", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    closure_document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    merged_into_id: Mapped[UUID | None] = mapped_column(ForeignKey("status_events.id"))
    current_fact_set_id: Mapped[UUID | None] = mapped_column(nullable=True)
    current_brief_id: Mapped[UUID | None] = mapped_column(nullable=True)


class StatusMatchWatch(Base, TimestampMixin):
    __tablename__ = "statusmatch_watches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    host: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    current_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("status_events.id"), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class StatusMatchWatchPage(Base, TimestampMixin):
    __tablename__ = "statusmatch_watch_pages"
    __table_args__ = (
        UniqueConstraint("watch_id", "page_kind"),
        UniqueConstraint("canonical_url"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    watch_id: Mapped[UUID] = mapped_column(
        ForeignKey("statusmatch_watches.id", ondelete="CASCADE"), nullable=False
    )
    page_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    current_document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class StatusMatchChangeSet(Base, TimestampMixin):
    __tablename__ = "statusmatch_change_sets"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "activity_document_version_id",
            "faq_document_version_id",
            "terms_document_version_id",
            "to_fact_set_id",
            name="uq_statusmatch_change_sets_event_snapshot_fact",
        ),
        Index("ix_statusmatch_change_sets_event_created", "event_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("status_events.id"), nullable=False
    )
    from_fact_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fact_sets.id"), nullable=True
    )
    to_fact_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("fact_sets.id"), nullable=False
    )
    activity_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    faq_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    terms_document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


class StatusMatchArticleRoute(Base, TimestampMixin):
    __tablename__ = "statusmatch_article_routes"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "project_host",
            name="uq_statusmatch_article_route_document_host",
        ),
        Index("ix_statusmatch_article_routes_event_status", "event_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    project_host: Mapped[str] = mapped_column(String(255), nullable=False)
    project_url: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("status_events.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(40), default="DISCOVERED", nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class StatusMatchArticleSupplement(Base, TimestampMixin):
    __tablename__ = "statusmatch_article_supplements"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "fact_set_id",
            "brief_id",
            "input_version",
            name="uq_statusmatch_article_supplement_input",
        ),
        Index(
            "ix_statusmatch_article_supplements_event_fact",
            "event_id",
            "fact_set_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    route_id: Mapped[UUID] = mapped_column(
        ForeignKey("statusmatch_article_routes.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("status_events.id"), nullable=False
    )
    article_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    fact_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("fact_sets.id"), nullable=False
    )
    brief_id: Mapped[UUID] = mapped_column(
        ForeignKey("briefs.id"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=False
    )
    input_version: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    highlights: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    mapping_claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )


class EventRevision(Base, TimestampMixin):
    __tablename__ = "event_revisions"
    __table_args__ = (
        UniqueConstraint("event_id", "document_version_id", "relationship"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("status_events.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(50), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class EventEvidence(Base, TimestampMixin):
    __tablename__ = "event_evidence"
    __table_args__ = (
        UniqueConstraint("event_id", "document_version_id", "hint_index"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("status_events.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    hint_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)


class FactSetRecord(Base, TimestampMixin):
    __tablename__ = "fact_sets"
    __table_args__ = (UniqueConstraint("event_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("status_events.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    has_conflicts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BriefRecord(Base, TimestampMixin):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("fact_set_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fact_set_id: Mapped[UUID] = mapped_column(ForeignKey("fact_sets.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)


class ReviewDecision(Base, TimestampMixin):
    __tablename__ = "review_decisions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(200), default="operator", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class GoldCaseRecord(Base, TimestampMixin):
    __tablename__ = "gold_cases"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_text: Mapped[str] = mapped_column(Text, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# Register the source-neutral knowledge tables with the same metadata/migrations.
from journeyplus.knowledge import models as _knowledge_models  # noqa: E402,F401
from journeyplus import workspace_models as _workspace_models  # noqa: E402,F401
