from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
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
