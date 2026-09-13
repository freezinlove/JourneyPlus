from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.article_operations import (
    pending_article_documents,
    process_pending_articles,
)
from journeyplus.automation.service import (
    AutomationLimits,
    BudgetedAIProvider,
    acquire_automation_lease,
    release_automation_lease,
)
from journeyplus.contracts import RunStatus
from journeyplus.lifecycle.service import BEIJING_TZ
from journeyplus.models import (
    CollectionRun,
    DocumentVersion,
    InitializationRun,
    SourceItem,
)
from journeyplus.sources.base import Fetcher, HttpxFetcher, SourceAdapter
from journeyplus.sources.collection import collect_in_phases
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.history import HistoricalFeedWindowAdapter
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.project_workflow import (
    StatusMatchProjectProcessingSummary,
    pending_statusmatch_project_count,
    process_pending_statusmatch_projects,
)
from journeyplus.statusmatch.article_workflow import (
    StatusMatchArticleProcessingSummary,
    pending_statusmatch_article_count,
    process_pending_statusmatch_articles,
)
from journeyplus.statusmatch.articles import (
    ArticleProjectPreparationSummary,
    ArticleRouteDiscoverySummary,
    discover_statusmatch_article_routes,
)


MAIL_SOURCE_ID = "status_services_mail"
PUBLIC_FEED_SOURCE_IDS = (
    "loyaltylobby_feed",
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
    document_version_ids: tuple[str, ...] = ()
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


def run_mail_detail_initialization(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    limits: AutomationLimits | None = None,
    now: datetime | None = None,
    statusmatch_fetcher: Fetcher | None = None,
) -> InitializationSummary:
    return _run_initialization(
        session_factory,
        provider,
        adapter_factory,
        batch_key="initialization:mail-details",
        batch_type="MAIL_DETAILS",
        source_ids=(MAIL_SOURCE_ID,),
        start=None,
        end=None,
        limits=limits or AutomationLimits(source_items_per_source=500),
        now=now,
        statusmatch_fetcher=statusmatch_fetcher,
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
    statusmatch_fetcher: Fetcher | None = None,
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
        statusmatch_fetcher=statusmatch_fetcher,
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
    statusmatch_fetcher: Fetcher | None,
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
    project_processing = StatusMatchProjectProcessingSummary()
    article_discovery = ArticleRouteDiscoverySummary()
    article_preparation = ArticleProjectPreparationSummary()
    article_processing = StatusMatchArticleProcessingSummary()
    project_hosts: tuple[str, ...] = ()
    backlog = 0
    error: str | None = None
    attempt = 0
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
            attempt = run.attempts
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
                    batch_key=f"{batch_key}:run:{run_id}:attempt:{attempt}",
                    start=start,
                    end=end,
                    max_items=limits.source_items_per_source,
                    now=current,
                    article_provider=budgeted,
                )
            )

        source_failed = any(item.status == RunStatus.FAILED for item in source_results)
        current_document_ids = tuple(
            document_id
            for item in source_results
            for document_id in item.document_version_ids
        )
        if batch_type == "MAIL_DETAILS":
            with session_factory() as session:
                project_hosts = _statusmatch_hosts_for_documents(
                    session, current_document_ids
                )
        elif not source_failed:
            with session_factory.begin() as session:
                article_discovery = discover_statusmatch_article_routes(
                    session,
                    source_ids=list(source_ids),
                    document_ids=current_document_ids,
                )
            from journeyplus.statusmatch.articles import prepare_article_projects_in_phases
            article_preparation = prepare_article_projects_in_phases(
                session_factory, statusmatch_fetcher or HttpxFetcher(),
                hosts=list(article_discovery.project_hosts), checked_at=current
            )
            project_hosts = article_discovery.project_hosts
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
            if project_hosts:
                project_processing = process_pending_statusmatch_projects(
                    session_factory,
                    budgeted,
                    hosts=project_hosts,
                    limit=limits.documents,
                )
            article_limit = limits.documents - project_processing.attempted
            if article_limit > 0:
                article_processing = process_pending_statusmatch_articles(
                    session_factory,
                    budgeted,
                    limit=article_limit,
                    hosts=project_hosts or None,
                )
            generic_limit = (
                limits.documents
                - project_processing.attempted
                - article_processing.attempted
            )
            generic_payload: dict[str, Any] = {
                "selected": 0,
                "attempted": 0,
                "succeeded": 0,
                "failed": 0,
                "stopped_early": False,
                "status_opportunities": 0,
                "opportunities": 0,
                "briefs": 0,
            }
            if generic_limit > 0 and batch_type == "PUBLIC_WINDOW":
                processing = process_pending_articles(
                    session_factory,
                    budgeted,
                    document_ids=current_document_ids,
                    published_from=published_from,
                    published_until=published_until,
                    limit=generic_limit,
                    stop_on_failure=True,
                )
                generic_payload = asdict(processing)
            processing_payload = {
                "selected": (
                    project_processing.selected
                    + article_processing.selected
                    + generic_payload["selected"]
                ),
                "attempted": (
                    project_processing.attempted
                    + article_processing.attempted
                    + generic_payload["attempted"]
                ),
                "succeeded": (
                    project_processing.succeeded
                    + article_processing.succeeded
                    + generic_payload["succeeded"]
                ),
                "failed": (
                    project_processing.failed
                    + article_processing.failed
                    + generic_payload["failed"]
                ),
                "stopped_early": generic_payload["stopped_early"],
                "status_opportunities": generic_payload["status_opportunities"],
                "opportunities": generic_payload["opportunities"],
                "briefs": generic_payload["briefs"],
                "statusmatch_projects": asdict(project_processing),
                "statusmatch_article_discovery": asdict(article_discovery),
                "statusmatch_article_preparation": asdict(article_preparation),
                "statusmatch_articles": asdict(article_processing),
                "generic_documents": generic_payload,
            }
            if processing_payload["failed"]:
                error = (
                    f"{processing_payload['failed']} initialization items failed"
                )

        with session_factory.begin() as session:
            published_from, published_until = _window_bounds(start, end)
            backlog = (
                len(
                    pending_article_documents(
                        session,
                        budgeted,
                        document_ids=current_document_ids,
                        published_from=published_from,
                        published_until=published_until,
                        limit=None,
                    )
                )
                if batch_type == "PUBLIC_WINDOW"
                else 0
            )
            if batch_type == "MAIL_DETAILS":
                backlog += pending_statusmatch_project_count(
                    session,
                    budgeted,
                    hosts=project_hosts,
                )
            else:
                backlog += pending_statusmatch_article_count(
                    session,
                    budgeted,
                    hosts=project_hosts or None,
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
    article_provider=None,
) -> InitializationSourceSummary:
    key = f"{batch_key}:{source_id}"
    historical: HistoricalFeedWindowAdapter | None = None
    try:
        adapter = adapter_factory(source_id)
        if start is not None and end is not None:
            if not isinstance(adapter, FeedAdapter):
                raise TypeError(f"{source_id} historical initialization requires FeedAdapter")
            historical = HistoricalFeedWindowAdapter(adapter,start=start,end=end)
            adapter = historical
        collection = collect_in_phases(session_factory,adapter,idempotency_key=key,max_items=max_items,
                                      article_provider=article_provider)
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
            document_version_ids=collection.current_document_version_ids,
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
    if batch_type == "MAIL_DETAILS":
        return
    assert start is not None
    if start == INITIALIZATION_START:
        previous_key = "initialization:mail-details"
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


def _statusmatch_hosts_for_documents(
    session: Session,
    document_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not document_ids:
        return ()
    external_ids = session.scalars(
        select(SourceItem.external_id)
        .join(DocumentVersion, DocumentVersion.source_item_id == SourceItem.id)
        .where(
            DocumentVersion.id.in_([UUID(value) for value in document_ids]),
            SourceItem.source_id == MAIL_SOURCE_ID,
            SourceItem.external_id.startswith("statusmatch-page:"),
        )
    )
    hosts: list[str] = []
    for external_id in external_ids:
        identity = external_id.removeprefix("statusmatch-page:")
        host, separator, page_kind = identity.rpartition(":")
        if separator and host and page_kind in {"activity", "faq", "terms"}:
            hosts.append(host.casefold().rstrip("."))
    return tuple(dict.fromkeys(hosts))


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
