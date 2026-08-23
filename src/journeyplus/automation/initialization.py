from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.automation.service import (
    AutomationLimits,
    BudgetedAIProvider,
    acquire_automation_lease,
    release_automation_lease,
)
from journeyplus.contracts import RunStatus
from journeyplus.lifecycle.service import BEIJING_TZ
from journeyplus.models import CollectionRun, InitializationRun
from journeyplus.operations import pending_document_count, process_pending_documents
from journeyplus.sources.base import SourceAdapter
from journeyplus.sources.collection import CollectionSummary, collect_manual
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.history import HistoricalFeedWindowAdapter
from journeyplus.sources.registry import seed_sources


CATALOG_SOURCE_ID = "ffb_status_match_catalog"
PUBLIC_FEED_SOURCE_IDS = (
    "ffb_elite_status_feed",
    "awardwallet_elite_status_feed",
    "loyaltylobby_feed",
    "frequentmiler_elite_status_feed",
    "verylvke_feed",
)
INITIALIZATION_START = date(2026, 7, 15)
INITIALIZATION_END = date(2026, 8, 22)


@dataclass(frozen=True, slots=True)
class InitializationSourceSummary:
    source_id: str
    status: str
    discovered: int = 0
    considered: int = 0
    new_documents: int = 0
    reused: bool = False
    pages_scanned: int | None = None
    missing_published_at: int | None = None
    oldest_published_date: str | None = None
    newest_published_date: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class InitializationSummary:
    run_id: str | None
    batch_key: str
    batch_type: str
    window_start: str | None
    window_end: str | None
    status: str
    audit_status: str
    skipped: bool
    skip_reason: str | None
    sources: tuple[InitializationSourceSummary, ...]
    documents_selected: int
    documents_succeeded: int
    documents_failed: int
    model_calls: int
    backlog_count: int
    error: str | None


def run_catalog_initialization(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    limits: AutomationLimits | None = None,
    now: datetime | None = None,
) -> InitializationSummary:
    return _run_initialization(
        session_factory,
        provider,
        adapter_factory,
        batch_key="initialization:catalog",
        batch_type="CATALOG",
        source_ids=(CATALOG_SOURCE_ID,),
        start=None,
        end=None,
        limits=limits or AutomationLimits(source_items_per_source=500),
        now=now,
    )


def run_public_initialization_window(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    start: date,
    end: date,
    limits: AutomationLimits | None = None,
    now: datetime | None = None,
) -> InitializationSummary:
    _validate_window(start, end)
    batch_key = f"initialization:{start.isoformat()}:{end.isoformat()}"
    return _run_initialization(
        session_factory,
        provider,
        adapter_factory,
        batch_key=batch_key,
        batch_type="PUBLIC_WINDOW",
        source_ids=PUBLIC_FEED_SOURCE_IDS,
        start=start,
        end=end,
        limits=limits or AutomationLimits(source_items_per_source=500),
        now=now,
    )


def mark_initialization_audit(
    session_factory: sessionmaker[Session],
    *,
    batch_key: str,
    passed: bool,
    notes: str,
) -> None:
    with session_factory.begin() as session:
        run = session.scalar(
            select(InitializationRun).where(
                InitializationRun.batch_key == batch_key
            )
        )
        if run is None:
            raise LookupError(f"Initialization batch {batch_key!r} was not found")
        if run.status != "AWAITING_AUDIT":
            raise ValueError("only a completed batch awaiting audit can be decided")
        run.audit_status = "PASSED" if passed else "FAILED"
        run.status = "PASSED" if passed else "FAILED"
        run.audit_notes = notes[:4000]


def _run_initialization(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    batch_key: str,
    batch_type: str,
    source_ids: tuple[str, ...],
    start: date | None,
    end: date | None,
    limits: AutomationLimits,
    now: datetime | None,
) -> InitializationSummary:
    current = _as_utc(now or datetime.now(UTC))
    owner = f"initialization-{uuid4().hex}"
    if not acquire_automation_lease(
        session_factory,
        owner_id=owner,
        now=current,
        lease_duration=timedelta(hours=4),
    ):
        return _skipped(batch_key, batch_type, start, end, "active database lease")

    run_id: str | None = None
    source_results: list[InitializationSourceSummary] = []
    processing_payload: dict[str, Any] = {}
    budgeted = BudgetedAIProvider(provider, limits.model_calls)
    backlog = 0
    error: str | None = None
    try:
        with session_factory.begin() as session:
            seed_sources(session)
            _require_previous_batch_passed(session, batch_type, start)
            existing = session.scalar(
                select(InitializationRun).where(
                    InitializationRun.batch_key == batch_key
                )
            )
            if existing is not None and existing.status in {
                "AWAITING_AUDIT",
                "PASSED",
            }:
                return _summary_from_record(existing)
            run = existing or InitializationRun(
                batch_key=batch_key,
                batch_type=batch_type,
                window_start=start,
                window_end=end,
                status=RunStatus.PENDING,
            )
            if existing is None:
                session.add(run)
            run.status = RunStatus.RUNNING
            run.audit_status = "PENDING"
            run.attempts = (run.attempts or 0) + 1
            run.limits = asdict(limits)
            run.error = None
            run.started_at = current
            run.finished_at = None
            session.flush()
            run_id = str(run.id)

        for source_id in source_ids:
            source_results.append(
                _collect_initialization_source(
                    session_factory,
                    adapter_factory=adapter_factory,
                    source_id=source_id,
                    batch_key=batch_key,
                    start=start,
                    end=end,
                    max_items=limits.source_items_per_source,
                    now=current,
                )
            )

        source_failed = any(item.status == RunStatus.FAILED for item in source_results)
        if source_failed:
            error = "one or more initialization sources failed"
            processing_payload = {
                "selected": 0,
                "succeeded": 0,
                "failed": 0,
                "skipped_reason": "source collection or historical coverage failed",
            }
        else:
            published_from, published_until = _window_bounds(start, end)
            processing = process_pending_documents(
                session_factory,
                budgeted,
                source_id=CATALOG_SOURCE_ID if batch_type == "CATALOG" else None,
                source_ids=list(source_ids) if batch_type == "PUBLIC_WINDOW" else None,
                published_from=published_from,
                published_until=published_until,
                limit=limits.documents,
                stop_on_failure=True,
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
            if processing.failed:
                error = f"{processing.failed} initialization documents failed"

        with session_factory.begin() as session:
            published_from, published_until = _window_bounds(start, end)
            backlog = pending_document_count(
                session,
                budgeted,
                source_id=CATALOG_SOURCE_ID if batch_type == "CATALOG" else None,
                source_ids=list(source_ids) if batch_type == "PUBLIC_WINDOW" else None,
                published_from=published_from,
                published_until=published_until,
            )
            run = session.get(InitializationRun, UUID(run_id))
            assert run is not None
            if error is None and backlog == 0:
                run.status = "AWAITING_AUDIT"
                run.audit_status = "PENDING"
            else:
                run.status = RunStatus.FAILED
                run.audit_status = "BLOCKED"
                if error is None:
                    error = f"{backlog} initialization documents remain pending"
            run.source_results = [asdict(item) for item in source_results]
            run.processing_result = {
                **processing_payload,
                "model_calls": budgeted.calls,
                "backlog_count": backlog,
            }
            run.error = error
            run.finished_at = current
            status = run.status
            audit_status = run.audit_status
    except (KeyboardInterrupt, SystemExit) as exc:
        error = _safe_error(exc)
        if run_id is not None:
            with session_factory.begin() as session:
                run = session.get(InitializationRun, UUID(run_id))
                if run is not None:
                    run.status = RunStatus.FAILED
                    run.audit_status = "BLOCKED"
                    run.error = error
                    run.finished_at = current
        raise
    except Exception as exc:
        error = _safe_error(exc)
        status = RunStatus.FAILED
        audit_status = "BLOCKED"
        if run_id is not None:
            with session_factory.begin() as session:
                run = session.get(InitializationRun, UUID(run_id))
                if run is not None:
                    run.status = RunStatus.FAILED
                    run.audit_status = "BLOCKED"
                    run.error = error
                    run.finished_at = current
    finally:
        release_automation_lease(session_factory, owner_id=owner, now=current)

    return InitializationSummary(
        run_id=run_id,
        batch_key=batch_key,
        batch_type=batch_type,
        window_start=start.isoformat() if start else None,
        window_end=end.isoformat() if end else None,
        status=str(status),
        audit_status=audit_status,
        skipped=False,
        skip_reason=None,
        sources=tuple(source_results),
        documents_selected=int(processing_payload.get("selected", 0)),
        documents_succeeded=int(processing_payload.get("succeeded", 0)),
        documents_failed=int(processing_payload.get("failed", 0)),
        model_calls=budgeted.calls,
        backlog_count=backlog,
        error=error,
    )


def _collect_initialization_source(
    session_factory: sessionmaker[Session],
    *,
    adapter_factory: Callable[[str], SourceAdapter],
    source_id: str,
    batch_key: str,
    start: date | None,
    end: date | None,
    max_items: int,
    now: datetime,
) -> InitializationSourceSummary:
    key = f"{batch_key}:{source_id}"
    historical: HistoricalFeedWindowAdapter | None = None
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
                adapter = adapter_factory(source_id)
                if start is not None and end is not None:
                    if not isinstance(adapter, FeedAdapter):
                        raise TypeError(
                            f"{source_id} historical initialization requires FeedAdapter"
                        )
                    historical = HistoricalFeedWindowAdapter(
                        adapter, start=start, end=end
                    )
                    adapter = historical
                collection = collect_manual(
                    session,
                    adapter,
                    idempotency_key=key,
                    max_items=max_items,
                )
        report = historical.report if historical is not None else None
        if report is not None and report.eligible > max_items:
            raise RuntimeError(
                f"{source_id} has {report.eligible} eligible items, above limit {max_items}"
            )
        return InitializationSourceSummary(
            source_id=source_id,
            status=RunStatus.SUCCEEDED,
            discovered=collection.discovered,
            considered=collection.considered,
            new_documents=collection.new_versions,
            reused=collection.reused_run,
            pages_scanned=report.pages_scanned if report else None,
            missing_published_at=report.missing_published_at if report else None,
            oldest_published_date=report.oldest_published_date if report else None,
            newest_published_date=report.newest_published_date if report else None,
        )
    except Exception as exc:
        error = _safe_error(exc)
        with session_factory.begin() as session:
            run = session.scalar(
                select(CollectionRun).where(CollectionRun.idempotency_key == key)
            )
            if run is None:
                run = CollectionRun(
                    source_id=source_id,
                    idempotency_key=key,
                    status=RunStatus.FAILED,
                )
                session.add(run)
            run.status = RunStatus.FAILED
            run.error = error
            run.started_at = run.started_at or now
            run.finished_at = now
        return InitializationSourceSummary(
            source_id=source_id,
            status=RunStatus.FAILED,
            error=error,
        )


def _require_previous_batch_passed(
    session: Session,
    batch_type: str,
    start: date | None,
) -> None:
    if batch_type == "CATALOG":
        return
    assert start is not None
    if start == INITIALIZATION_START:
        previous_key = "initialization:catalog"
    else:
        previous_start = start - timedelta(days=2)
        previous_end = min(previous_start + timedelta(days=1), INITIALIZATION_END)
        previous_key = (
            f"initialization:{previous_start.isoformat()}:{previous_end.isoformat()}"
        )
    previous = session.scalar(
        select(InitializationRun).where(
            InitializationRun.batch_key == previous_key
        )
    )
    if previous is None or previous.audit_status != "PASSED":
        raise RuntimeError(
            f"previous initialization batch {previous_key} has not passed audit"
        )


def _validate_window(start: date, end: date) -> None:
    if start < INITIALIZATION_START or end > INITIALIZATION_END or end < start:
        raise ValueError("initialization window is outside 2026-07-15 through 2026-08-22")
    offset = (start - INITIALIZATION_START).days
    expected_end = min(start + timedelta(days=1), INITIALIZATION_END)
    if offset % 2 or end != expected_end:
        raise ValueError("initialization window must be the next fixed two-day batch")


def _window_bounds(
    start: date | None,
    end: date | None,
) -> tuple[datetime | None, datetime | None]:
    if start is None or end is None:
        return None, None
    lower = datetime.combine(start, time.min, tzinfo=BEIJING_TZ)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=BEIJING_TZ)
    return lower.astimezone(UTC), upper.astimezone(UTC)


def _summary_from_record(run: InitializationRun) -> InitializationSummary:
    processing = run.processing_result or {}
    return InitializationSummary(
        run_id=str(run.id),
        batch_key=run.batch_key,
        batch_type=run.batch_type,
        window_start=run.window_start.isoformat() if run.window_start else None,
        window_end=run.window_end.isoformat() if run.window_end else None,
        status=run.status,
        audit_status=run.audit_status,
        skipped=True,
        skip_reason="batch already completed and cannot advance before audit",
        sources=tuple(
            InitializationSourceSummary(**item) for item in run.source_results
        ),
        documents_selected=int(processing.get("selected", 0)),
        documents_succeeded=int(processing.get("succeeded", 0)),
        documents_failed=int(processing.get("failed", 0)),
        model_calls=int(processing.get("model_calls", 0)),
        backlog_count=int(processing.get("backlog_count", 0)),
        error=run.error,
    )


def _skipped(
    batch_key: str,
    batch_type: str,
    start: date | None,
    end: date | None,
    reason: str,
) -> InitializationSummary:
    return InitializationSummary(
        run_id=None,
        batch_key=batch_key,
        batch_type=batch_type,
        window_start=start.isoformat() if start else None,
        window_end=end.isoformat() if end else None,
        status=RunStatus.SKIPPED,
        audit_status="PENDING",
        skipped=True,
        skip_reason=reason,
        sources=(),
        documents_selected=0,
        documents_succeeded=0,
        documents_failed=0,
        model_calls=0,
        backlog_count=0,
        error=None,
    )


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:1000]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
