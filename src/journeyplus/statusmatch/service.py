from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.service import IngestionService
from journeyplus.contracts import LifecycleStatus
from journeyplus.models import (
    DocumentVersion,
    SourceItem,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import Fetcher
from journeyplus.statusmatch.closure import (
    ClosureAssessment,
    assess_statusmatch_home_closure,
)
from journeyplus.statusmatch.fetching import fetch_statusmatch_page
from journeyplus.statusmatch.watchlist import (
    current_watch_documents,
    delete_watch_only,
    ensure_statusmatch_watch,
    record_statusmatch_page_error,
    record_statusmatch_page_result,
    resolve_watch_event,
    statusmatch_page_item,
)


@dataclass(frozen=True, slots=True)
class StatusMatchMonitoringSummary:
    projects_checked: int = 0
    pages_checked: int = 0
    pages_changed: int = 0
    projects_archived: int = 0
    changed_document_version_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def monitor_statusmatch_watches(
    session: Session,
    fetcher: Fetcher,
    *,
    checked_at: datetime | None = None,
    hosts: list[str] | tuple[str, ...] | None = None,
) -> StatusMatchMonitoringSummary:
    current = checked_at or datetime.now(UTC)
    statement = select(StatusMatchWatch)
    if hosts is not None:
        normalized_hosts = {host.casefold().rstrip(".") for host in hosts}
        statement = statement.where(StatusMatchWatch.host.in_(normalized_hosts))
    watches = list(session.scalars(statement.order_by(StatusMatchWatch.host.asc())))
    ingestion = IngestionService(session)
    pages_checked = 0
    pages_changed = 0
    archived = 0
    changed_document_version_ids: list[str] = []
    errors: list[str] = []
    for watch in watches:
        watch = ensure_statusmatch_watch(session, watch.host)
        watch_failed = False
        pages = {
            page.page_kind: page
            for page in session.scalars(
                select(StatusMatchWatchPage).where(
                    StatusMatchWatchPage.watch_id == watch.id
                )
            )
        }
        activity_page = pages.get("activity")
        if activity_page is None:
            watch.status = "PENDING"
            watch.last_error = "StatusMatch HOME watch page is missing"
            errors.append(f"{watch.host}:activity:LookupError: HOME watch page is missing")
            continue

        pages_checked += 1
        activity_item = statusmatch_page_item(
            host=watch.host,
            page_kind=activity_page.page_kind,
            canonical_url=activity_page.canonical_url,
            refresh=True,
        )
        try:
            activity_raw = fetch_statusmatch_page(activity_item, fetcher)
            activity_result = ingestion.ingest(activity_item, activity_raw)
            record_statusmatch_page_result(
                session,
                item=activity_item,
                result=activity_result,
                checked_at=current,
            )
            pages_changed += int(activity_result.new_version)
            if activity_result.new_version:
                changed_document_version_ids.append(
                    str(activity_result.document_version.id)
                )
        except Exception as exc:
            record_statusmatch_page_error(
                session,
                item=activity_item,
                error=exc,
                checked_at=current,
            )
            errors.append(
                f"{watch.host}:activity:{type(exc).__name__}: {exc}"[:1000]
            )
            continue

        if _archive_if_statusmatch_home_closed(
            session,
            watch=watch,
            checked_at=current,
        ):
            archived += 1
            continue

        for page_kind in ("faq", "terms"):
            page = pages.get(page_kind)
            if page is None:
                watch_failed = True
                watch.status = "PENDING"
                watch.last_error = f"StatusMatch {page_kind.upper()} watch page is missing"
                errors.append(
                    f"{watch.host}:{page_kind}:LookupError: watch page is missing"
                )
                continue
            pages_checked += 1
            item = statusmatch_page_item(
                host=watch.host,
                page_kind=page.page_kind,
                canonical_url=page.canonical_url,
                refresh=True,
            )
            try:
                raw = fetch_statusmatch_page(item, fetcher)
                result = ingestion.ingest(item, raw)
                record_statusmatch_page_result(
                    session,
                    item=item,
                    result=result,
                    checked_at=current,
                )
                pages_changed += int(result.new_version)
                if result.new_version:
                    changed_document_version_ids.append(
                        str(result.document_version.id)
                    )
            except Exception as exc:
                watch_failed = True
                record_statusmatch_page_error(
                    session,
                    item=item,
                    error=exc,
                    checked_at=current,
                )
                errors.append(
                    f"{watch.host}:{page.page_kind}:{type(exc).__name__}: {exc}"[:1000]
                )
        if not watch_failed and finalize_statusmatch_watch(
            session, watch.host, checked_at=current
        ):
            archived += 1
    return StatusMatchMonitoringSummary(
        projects_checked=len(watches),
        pages_checked=pages_checked,
        pages_changed=pages_changed,
        projects_archived=archived,
        changed_document_version_ids=tuple(changed_document_version_ids),
        errors=tuple(errors),
    )


def finalize_statusmatch_watch(
    session: Session,
    host: str,
    *,
    checked_at: datetime | None = None,
) -> bool:
    watch = session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.host == host)
    )
    if watch is None:
        return False
    if _archive_if_statusmatch_home_closed(
        session,
        watch=watch,
        checked_at=checked_at or datetime.now(UTC),
    ):
        return True
    pages = {
        page.page_kind: page
        for page in session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    }
    if set(pages) != {"activity", "faq", "terms"} or any(
        page.current_document_version_id is None or page.last_error is not None
        for page in pages.values()
    ):
        return False
    # HOME was checked above. FAQ/Terms only contribute content versions and
    # fetch health; their wording cannot close or suspend an otherwise open offer.
    watch.status = "ACTIVE"
    watch.last_error = None
    session.flush()
    return False


def _archive_and_remove_watch(
    session: Session,
    *,
    watch: StatusMatchWatch,
    assessment: ClosureAssessment,
    documents: dict[str, DocumentVersion],
    checked_at: datetime,
) -> None:
    event = resolve_watch_event(session, watch)
    evidence_kind = assessment.evidence_page_kind or "activity"
    evidence_document = documents[evidence_kind]
    if event is not None and event.archived_at is None:
        event.archived_at = checked_at
        event.lifecycle_status = LifecycleStatus.EXPIRED
        event.archive_reason = assessment.reason
        event.closure_document_version_id = evidence_document.id
    for document in current_watch_documents(session, watch):
        item = session.get(SourceItem, document.source_item_id)
        if item is not None:
            item.raw_metadata = {
                **(item.raw_metadata or {}),
                "skip_semantic_processing": True,
                "statusmatch_closure_reason": assessment.reason,
            }
    delete_watch_only(session, watch)


def _archive_if_statusmatch_home_closed(
    session: Session,
    *,
    watch: StatusMatchWatch,
    checked_at: datetime,
) -> bool:
    activity_page = session.scalar(
        select(StatusMatchWatchPage).where(
            StatusMatchWatchPage.watch_id == watch.id,
            StatusMatchWatchPage.page_kind == "activity",
        )
    )
    if (
        activity_page is None
        or activity_page.current_document_version_id is None
        or activity_page.last_error is not None
    ):
        return False
    activity, activity_item = _page_document_and_item(session, activity_page)
    assessment = assess_statusmatch_home_closure(
        activity=activity,
        activity_item=activity_item,
    )
    if not assessment.closed:
        return False
    _archive_and_remove_watch(
        session,
        watch=watch,
        assessment=assessment,
        documents={"activity": activity},
        checked_at=checked_at,
    )
    return True


def _page_document_and_item(
    session: Session,
    page: StatusMatchWatchPage,
) -> tuple[DocumentVersion, SourceItem]:
    document = session.get(DocumentVersion, page.current_document_version_id)
    if document is None:
        raise LookupError("Current StatusMatch document was not found")
    item = session.get(SourceItem, document.source_item_id)
    if item is None:
        raise LookupError("Current StatusMatch source item was not found")
    return document, item
