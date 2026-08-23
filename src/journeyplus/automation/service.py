from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import RunStatus
from journeyplus.lifecycle.service import BEIJING_TZ, advance_lifecycles
from journeyplus.models import (
    AutomationLease,
    AutomationRun,
    CollectionRun,
    JobRun,
    Source,
    SourceAutomationState,
    StatusEvent,
)
from journeyplus.operations import (
    pending_document_count,
    process_pending_documents,
)
from journeyplus.sources.base import SourceAdapter
from journeyplus.sources.collection import (
    CollectionSummary,
    automatically_scheduled_source_ids,
    collect_manual,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources


LEASE_NAME = "daily-source-automation"


@dataclass(frozen=True, slots=True)
class AutomationLimits:
    source_items_per_source: int = 100
    documents: int = 20
    model_calls: int = 100

    def __post_init__(self) -> None:
        if min(
            self.source_items_per_source,
            self.documents,
            self.model_calls,
        ) < 1:
            raise ValueError("automation limits must be positive")


@dataclass(frozen=True, slots=True)
class SourceCycleSummary:
    source_id: str
    status: str
    discovered: int = 0
    considered: int = 0
    new_documents: int = 0
    reused: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DailyCycleSummary:
    run_id: str | None
    day_bucket: str
    status: str
    skipped: bool
    skip_reason: str | None
    error: str | None
    sources: tuple[SourceCycleSummary, ...]
    documents_selected: int
    documents_succeeded: int
    documents_failed: int
    model_calls: int
    lifecycle_scanned: int
    lifecycle_updated: int
    lifecycle_expired: int
    backlog_count: int
    needs_review_count: int


@dataclass(frozen=True, slots=True)
class SourceStatusSummary:
    source_id: str
    enabled: bool
    automatic_scheduling: bool
    collection_cadence: str | None
    last_day_bucket: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    last_failure_at: str | None
    last_error: str | None
    consecutive_failures: int
    last_new_document_count: int
    pending_document_count: int


@dataclass(frozen=True, slots=True)
class AutomationStatusSummary:
    lease_owner: str | None
    lease_expires_at: str | None
    last_run_id: str | None
    last_run_day: str | None
    last_run_status: str | None
    backlog_count: int
    failed_job_count: int
    needs_review_count: int
    sources: tuple[SourceStatusSummary, ...]


class ModelCallBudgetExceeded(RuntimeError):
    pass


class BudgetedAIProvider:
    def __init__(self, provider: AIProvider, limit: int) -> None:
        if limit < 1:
            raise ValueError("model call limit must be positive")
        self._provider = provider
        self._limit = limit
        self.calls = 0
        self.metadata = provider.metadata

    def generate_structured(self, **kwargs):
        if self.calls >= self._limit:
            raise ModelCallBudgetExceeded(
                f"daily model call limit {self._limit} was reached"
            )
        self.calls += 1
        return self._provider.generate_structured(**kwargs)


def run_daily_cycle(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    limits: AutomationLimits | None = None,
    now: datetime | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    lease_duration: timedelta = timedelta(hours=1),
    owner_id: str | None = None,
) -> DailyCycleSummary:
    resolved_limits = limits or AutomationLimits()
    current = _as_utc(now or datetime.now(UTC))
    day_bucket = current.astimezone(BEIJING_TZ).date()
    owner = owner_id or uuid4().hex
    if not acquire_automation_lease(
        session_factory,
        owner_id=owner,
        now=current,
        lease_duration=lease_duration,
    ):
        return _skipped_summary(day_bucket, "active database lease")

    run_id: str | None = None
    source_summaries: list[SourceCycleSummary] = []
    processing_payload: dict[str, Any] = {}
    lifecycle_payload: dict[str, int] = {"scanned": 0, "updated": 0, "expired": 0}
    budgeted = BudgetedAIProvider(provider, resolved_limits.model_calls)
    backlog = 0
    needs_review = 0
    global_error: str | None = None
    try:
        with session_factory.begin() as session:
            seed_sources(session)
            selected_source_ids = _selected_source_ids(session, source_ids)
            run = _start_run(
                session,
                day_bucket=day_bucket,
                owner_id=owner,
                limits=resolved_limits,
                now=current,
            )
            run_id = str(run.id)

        for source_id in selected_source_ids:
            summary = _run_source_collection(
                session_factory,
                source_id=source_id,
                day_bucket=day_bucket,
                adapter_factory=adapter_factory,
                max_items=resolved_limits.source_items_per_source,
                now=current,
            )
            source_summaries.append(summary)

        try:
            processing = process_pending_documents(
                session_factory,
                budgeted,
                limit=resolved_limits.documents,
            )
            processing_payload = {
                "selected": processing.selected,
                "attempted": processing.attempted,
                "succeeded": processing.succeeded,
                "failed": processing.failed,
                "stopped_early": processing.stopped_early,
                "status_opportunities": processing.status_opportunities,
                "events": processing.events,
                "briefs": processing.briefs,
            }
        except Exception as exc:
            global_error = _safe_error(exc)
            processing_payload = {
                "selected": 0,
                "succeeded": 0,
                "failed": 1,
                "error": global_error,
            }

        with session_factory.begin() as session:
            lifecycle = advance_lifecycles(session, now=current)
            lifecycle_payload = asdict(lifecycle)
            backlog = pending_document_count(session, budgeted)
            needs_review = int(
                session.scalar(
                    select(func.count())
                    .select_from(StatusEvent)
                    .where(StatusEvent.status == "NEEDS_REVIEW")
                )
                or 0
            )
            _refresh_pending_states(session, budgeted)
            run = session.get(AutomationRun, run.id)
            assert run is not None
            source_failures = sum(
                item.status == RunStatus.FAILED for item in source_summaries
            )
            processing_failures = int(processing_payload.get("failed", 0))
            run.status = (
                RunStatus.SUCCEEDED
                if not source_failures and not processing_failures and not global_error
                else RunStatus.FAILED
            )
            run.source_results = [asdict(item) for item in source_summaries]
            run.processing_result = processing_payload
            run.lifecycle_result = lifecycle_payload
            run.model_calls = budgeted.calls
            run.backlog_count = backlog
            run.needs_review_count = needs_review
            run.error = global_error
            run.finished_at = current
            final_status = run.status
    except Exception as exc:
        global_error = _safe_error(exc)
        final_status = RunStatus.FAILED
        if run_id is not None:
            with session_factory.begin() as session:
                run = session.get(AutomationRun, UUID(run_id))
                if run is not None:
                    run.status = RunStatus.FAILED
                    run.error = global_error
                    run.finished_at = current
    finally:
        release_automation_lease(session_factory, owner_id=owner, now=current)

    return DailyCycleSummary(
        run_id=run_id,
        day_bucket=day_bucket.isoformat(),
        status=str(final_status),
        skipped=False,
        skip_reason=None,
        error=global_error,
        sources=tuple(source_summaries),
        documents_selected=int(processing_payload.get("selected", 0)),
        documents_succeeded=int(processing_payload.get("succeeded", 0)),
        documents_failed=int(processing_payload.get("failed", 0)),
        model_calls=budgeted.calls,
        lifecycle_scanned=lifecycle_payload["scanned"],
        lifecycle_updated=lifecycle_payload["updated"],
        lifecycle_expired=lifecycle_payload["expired"],
        backlog_count=backlog,
        needs_review_count=needs_review,
    )


def automation_status(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
) -> AutomationStatusSummary:
    with session_factory.begin() as session:
        sources = seed_sources(session)
        _ensure_source_states(session, [source.id for source in sources])
        lease = session.get(AutomationLease, LEASE_NAME)
        last_run = session.scalar(
            select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(1)
        )
        states = {
            state.source_id: state
            for state in session.scalars(select(SourceAutomationState))
        }
        backlog = pending_document_count(session, provider)
        failed_jobs = int(
            session.scalar(
                select(func.count())
                .select_from(JobRun)
                .where(JobRun.status == RunStatus.FAILED)
            )
            or 0
        )
        needs_review = int(
            session.scalar(
                select(func.count())
                .select_from(StatusEvent)
                .where(StatusEvent.status == "NEEDS_REVIEW")
            )
            or 0
        )
        source_results = tuple(
            _source_status(source, states[source.id]) for source in sources
        )
        return AutomationStatusSummary(
            lease_owner=lease.owner_id if lease else None,
            lease_expires_at=_iso(lease.expires_at) if lease else None,
            last_run_id=str(last_run.id) if last_run else None,
            last_run_day=last_run.day_bucket.isoformat() if last_run else None,
            last_run_status=last_run.status if last_run else None,
            backlog_count=backlog,
            failed_job_count=failed_jobs,
            needs_review_count=needs_review,
            sources=source_results,
        )


def acquire_automation_lease(
    session_factory: sessionmaker[Session],
    *,
    owner_id: str,
    now: datetime,
    lease_duration: timedelta,
) -> bool:
    if lease_duration <= timedelta(0):
        raise ValueError("lease duration must be positive")
    current = _as_utc(now)
    for _attempt in range(3):
        try:
            with session_factory.begin() as session:
                lease = session.scalar(
                    select(AutomationLease)
                    .where(AutomationLease.name == LEASE_NAME)
                    .with_for_update()
                )
                if lease is None:
                    session.add(
                        AutomationLease(
                            name=LEASE_NAME,
                            owner_id=owner_id,
                            acquired_at=current,
                            expires_at=current + lease_duration,
                        )
                    )
                    session.flush()
                    return True
                if (
                    lease.owner_id is not None
                    and lease.owner_id != owner_id
                    and lease.expires_at is not None
                    and _as_utc(lease.expires_at) > current
                ):
                    return False
                lease.owner_id = owner_id
                lease.acquired_at = current
                lease.expires_at = current + lease_duration
                return True
        except IntegrityError:
            continue
    return False


def release_automation_lease(
    session_factory: sessionmaker[Session],
    *,
    owner_id: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        lease = session.scalar(
            select(AutomationLease)
            .where(AutomationLease.name == LEASE_NAME)
            .with_for_update()
        )
        if lease is not None and lease.owner_id == owner_id:
            lease.owner_id = None
            lease.expires_at = _as_utc(now)


def _run_source_collection(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    adapter_factory: Callable[[str], SourceAdapter],
    max_items: int,
    now: datetime,
) -> SourceCycleSummary:
    key = f"daily:{day_bucket.isoformat()}:{source_id}"
    try:
        with session_factory.begin() as session:
            existing = session.scalar(
                select(CollectionRun).where(CollectionRun.idempotency_key == key)
            )
            if existing is not None and existing.status == RunStatus.SUCCEEDED:
                collection = CollectionSummary(
                    run_id=str(existing.id),
                    source_id=source_id,
                    discovered=existing.discovered_count,
                    considered=min(existing.discovered_count, max_items),
                    new_versions=existing.document_count,
                    reused_run=True,
                )
            else:
                collection = collect_manual(
                    session,
                    adapter_factory(source_id),
                    idempotency_key=key,
                    max_items=max_items,
                )
        _record_source_success(
            session_factory,
            source_id=source_id,
            day_bucket=day_bucket,
            new_documents=collection.new_versions,
            now=now,
        )
        return SourceCycleSummary(
            source_id=source_id,
            status=RunStatus.SUCCEEDED,
            discovered=collection.discovered,
            considered=collection.considered,
            new_documents=collection.new_versions,
            reused=collection.reused_run,
        )
    except Exception as exc:
        error = _safe_error(exc)
        _record_collection_failure(
            session_factory,
            source_id=source_id,
            idempotency_key=key,
            error=error,
            now=now,
        )
        _record_source_failure(
            session_factory,
            source_id=source_id,
            day_bucket=day_bucket,
            error=error,
            now=now,
        )
        return SourceCycleSummary(
            source_id=source_id,
            status=RunStatus.FAILED,
            error=error,
        )


def _record_collection_failure(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    idempotency_key: str,
    error: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        run = session.scalar(
            select(CollectionRun).where(
                CollectionRun.idempotency_key == idempotency_key
            )
        )
        if run is None:
            run = CollectionRun(
                source_id=source_id,
                idempotency_key=idempotency_key,
                status=RunStatus.FAILED,
            )
            session.add(run)
        run.status = RunStatus.FAILED
        run.error = error
        run.started_at = run.started_at or now
        run.finished_at = now


def _record_source_success(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    new_documents: int,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        state = _source_state(session, source_id)
        state.last_day_bucket = day_bucket
        state.last_attempt_at = now
        state.last_success_at = now
        state.last_error = None
        state.consecutive_failures = 0
        state.last_new_document_count = new_documents


def _record_source_failure(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    error: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        state = _source_state(session, source_id)
        state.last_day_bucket = day_bucket
        state.last_attempt_at = now
        state.last_failure_at = now
        state.last_error = error
        state.consecutive_failures += 1
        state.last_new_document_count = 0


def _refresh_pending_states(session: Session, provider: AIProvider) -> None:
    source_ids = [item.source_id for item in SOURCE_REGISTRY]
    _ensure_source_states(session, source_ids)
    for source_id in source_ids:
        state = session.get(SourceAutomationState, source_id)
        assert state is not None
        state.pending_document_count = pending_document_count(
            session, provider, source_id=source_id
        )


def _source_state(session: Session, source_id: str) -> SourceAutomationState:
    state = session.get(SourceAutomationState, source_id)
    if state is None:
        state = SourceAutomationState(source_id=source_id)
        session.add(state)
        session.flush()
    return state


def _ensure_source_states(session: Session, source_ids: list[str]) -> None:
    for source_id in source_ids:
        _source_state(session, source_id)


def _selected_source_ids(
    session: Session,
    source_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if source_ids is None:
        return automatically_scheduled_source_ids(session)
    known = {item.source_id for item in SOURCE_REGISTRY}
    unknown = set(source_ids) - known
    if unknown:
        raise ValueError(f"Unknown automation sources: {sorted(unknown)}")
    return list(dict.fromkeys(source_ids))


def _start_run(
    session: Session,
    *,
    day_bucket: date,
    owner_id: str,
    limits: AutomationLimits,
    now: datetime,
) -> AutomationRun:
    key = f"daily:{day_bucket.isoformat()}"
    run = session.scalar(
        select(AutomationRun).where(AutomationRun.idempotency_key == key)
    )
    if run is None:
        run = AutomationRun(
            idempotency_key=key,
            day_bucket=day_bucket,
            status=RunStatus.PENDING,
            owner_id=owner_id,
        )
        session.add(run)
    run.status = RunStatus.RUNNING
    run.attempts = (run.attempts or 0) + 1
    run.owner_id = owner_id
    run.limits = asdict(limits)
    run.error = None
    run.started_at = now
    run.finished_at = None
    session.flush()
    return run


def _source_status(
    source: Source,
    state: SourceAutomationState,
) -> SourceStatusSummary:
    return SourceStatusSummary(
        source_id=source.id,
        enabled=source.enabled,
        automatic_scheduling=source.automatic_scheduling,
        collection_cadence=source.collection_cadence,
        last_day_bucket=(
            state.last_day_bucket.isoformat() if state.last_day_bucket else None
        ),
        last_attempt_at=_iso(state.last_attempt_at),
        last_success_at=_iso(state.last_success_at),
        last_failure_at=_iso(state.last_failure_at),
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
        last_new_document_count=state.last_new_document_count,
        pending_document_count=state.pending_document_count,
    )


def _skipped_summary(day_bucket: date, reason: str) -> DailyCycleSummary:
    return DailyCycleSummary(
        run_id=None,
        day_bucket=day_bucket.isoformat(),
        status=RunStatus.SKIPPED,
        skipped=True,
        skip_reason=reason,
        error=None,
        sources=(),
        documents_selected=0,
        documents_succeeded=0,
        documents_failed=0,
        model_calls=0,
        lifecycle_scanned=0,
        lifecycle_updated=0,
        lifecycle_expired=0,
        backlog_count=0,
        needs_review_count=0,
    )


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:1000]


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
