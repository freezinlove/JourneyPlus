from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.service import IngestionService
from journeyplus.models import (
    DocumentVersion,
    SourceItem,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import Fetcher
from journeyplus.statusmatch.closure import (
    ClosureAssessment,
    assess_statusmatch_closure,
)
from journeyplus.statusmatch.fetching import fetch_statusmatch_page
from journeyplus.statusmatch.watchlist import (
    current_watch_documents,
    delete_watch_only,
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
) -> StatusMatchMonitoringSummary:
    current = checked_at or datetime.now(UTC)
    watches = list(
        session.scalars(select(StatusMatchWatch).order_by(StatusMatchWatch.host.asc()))
    )
    ingestion = IngestionService(session)
    pages_checked = 0
    pages_changed = 0
    archived = 0
    changed_document_version_ids: list[str] = []
    errors: list[str] = []
    for watch in watches:
        watch_failed = False
        pages = list(
            session.scalars(
                select(StatusMatchWatchPage)
                .where(StatusMatchWatchPage.watch_id == watch.id)
                .order_by(StatusMatchWatchPage.page_kind.asc())
            )
        )
        for page in pages:
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
    pages = {
        page.page_kind: page
        for page in session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    }
    if set(pages) != {"activity", "faq"} or any(
        page.current_document_version_id is None or page.last_error is not None
        for page in pages.values()
    ):
        return False
    activity, activity_item = _page_document_and_item(session, pages["activity"])
    faq, faq_item = _page_document_and_item(session, pages["faq"])
    assessment = assess_statusmatch_closure(
        activity=activity,
        activity_item=activity_item,
        faq=faq,
        faq_item=faq_item,
    )
    if not assessment.closed:
        watch.status = "ACTIVE"
        watch.last_error = None
        session.flush()
        return False
    _archive_and_remove_watch(
        session,
        watch=watch,
        assessment=assessment,
        documents={"activity": activity, "faq": faq},
        checked_at=checked_at or datetime.now(UTC),
    )
    return True


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
    if event is not None:
        event.archived_at = checked_at
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
