from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.service import IngestionResult
from journeyplus.contracts import DiscoveredItem
from journeyplus.models import (
    DocumentVersion,
    EventEvidence,
    SourceItem,
    StatusEvent,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.statusmatch_links import (
    is_project_statusmatch_host,
    statusmatch_project_page_urls,
)


MAIL_SOURCE_ID = "status_services_mail"
PAGE_EXTERNAL_ID_PREFIX = "statusmatch-page:"


def successful_gmail_message_ids(session: Session) -> set[str]:
    return set(
        session.scalars(
            select(SourceItem.external_id)
            .join(
                DocumentVersion,
                DocumentVersion.source_item_id == SourceItem.id,
            )
            .where(
                SourceItem.source_id == MAIL_SOURCE_ID,
                ~SourceItem.external_id.startswith(PAGE_EXTERNAL_ID_PREFIX),
            )
            .distinct()
        )
    )


def watched_statusmatch_hosts(session: Session) -> set[str]:
    return set(session.scalars(select(StatusMatchWatch.host)))


def ensure_statusmatch_watch(
    session: Session,
    host: str,
) -> StatusMatchWatch:
    normalized_host = host.casefold().rstrip(".")
    if not is_project_statusmatch_host(normalized_host):
        raise ValueError("StatusMatch watch host is not project-specific")
    watch = session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.host == normalized_host)
    )
    if watch is None:
        watch = StatusMatchWatch(host=normalized_host, status="PENDING")
        session.add(watch)
        session.flush()
    existing = {
        page.page_kind: page
        for page in session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    }
    for page_kind, canonical_url in statusmatch_project_page_urls(normalized_host):
        page = existing.get(page_kind)
        if page is None:
            session.add(
                StatusMatchWatchPage(
                    watch_id=watch.id,
                    page_kind=page_kind,
                    canonical_url=canonical_url,
                )
            )
        elif page.canonical_url != canonical_url:
            page.canonical_url = canonical_url
    session.flush()
    return watch


def statusmatch_page_item(
    *,
    host: str,
    page_kind: str,
    canonical_url: str,
    refresh: bool,
) -> DiscoveredItem:
    return DiscoveredItem(
        source_id=MAIL_SOURCE_ID,
        external_id=f"{PAGE_EXTERNAL_ID_PREFIX}{host}:{page_kind}",
        discovered_url=canonical_url,
        canonical_url=canonical_url,
        title=f"{host} StatusMatch {page_kind}",
        raw_metadata={
            "document_role": "linked_statusmatch_page",
            "page_kind": page_kind,
            "project_host": host,
            "managed_statusmatch_snapshot": True,
            "refresh_on_discovery": refresh,
        },
    )


def record_statusmatch_page_result(
    session: Session,
    *,
    item: DiscoveredItem,
    result: IngestionResult,
    checked_at: datetime | None = None,
) -> None:
    host, page_kind = statusmatch_page_identity(item)
    watch = ensure_statusmatch_watch(session, host)
    page = _watch_page(session, watch.id, page_kind)
    current = checked_at or datetime.now(UTC)
    page.current_document_version_id = result.document_version.id
    page.last_checked_at = current
    page.last_error = None
    if result.new_version:
        page.last_changed_at = current
        watch.last_changed_at = current
    watch.last_checked_at = current
    watch.last_error = _watch_error(session, watch.id)
    if _watch_has_both_documents(session, watch.id):
        watch.status = "ACTIVE"
    session.flush()


def record_statusmatch_page_error(
    session: Session,
    *,
    item: DiscoveredItem,
    error: Exception,
    checked_at: datetime | None = None,
) -> None:
    host, page_kind = statusmatch_page_identity(item)
    watch = ensure_statusmatch_watch(session, host)
    page = _watch_page(session, watch.id, page_kind)
    current = checked_at or datetime.now(UTC)
    message = f"{type(error).__name__}: {error}"[:1000]
    page.last_checked_at = current
    page.last_error = message
    watch.last_checked_at = current
    watch.last_error = message
    session.flush()


def statusmatch_page_identity(item: DiscoveredItem) -> tuple[str, str]:
    metadata = item.raw_metadata
    host = str(metadata.get("project_host") or "").casefold().rstrip(".")
    page_kind = str(metadata.get("page_kind") or "")
    if not is_project_statusmatch_host(host) or page_kind not in {"activity", "faq"}:
        raise ValueError("Item is not a managed StatusMatch activity or FAQ page")
    return host, page_kind


def watch_for_event(session: Session, event_id: UUID) -> StatusMatchWatch | None:
    return session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.current_event_id == event_id)
    )


def current_watch_documents(
    session: Session,
    watch: StatusMatchWatch,
) -> list[DocumentVersion]:
    document_ids = list(
        session.scalars(
            select(StatusMatchWatchPage.current_document_version_id)
            .where(
                StatusMatchWatchPage.watch_id == watch.id,
                StatusMatchWatchPage.current_document_version_id.is_not(None),
            )
            .order_by(StatusMatchWatchPage.page_kind.asc())
        )
    )
    if not document_ids:
        return []
    documents = {
        document.id: document
        for document in session.scalars(
            select(DocumentVersion).where(DocumentVersion.id.in_(document_ids))
        )
    }
    return [documents[document_id] for document_id in document_ids]


def associate_watch_event(
    session: Session,
    *,
    document: DocumentVersion,
    event: StatusEvent,
) -> None:
    item = session.get(SourceItem, document.source_item_id)
    if item is None:
        return
    identity = _source_item_page_identity(item)
    if identity is None:
        return
    host, _ = identity
    watch = session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.host == host)
    )
    if watch is None:
        return
    if watch.current_event_id is None:
        watch.current_event_id = event.id
    elif watch.current_event_id != event.id:
        current = session.get(StatusEvent, watch.current_event_id)
        event.status = "NEEDS_REVIEW"
        if current is not None:
            current.status = "NEEDS_REVIEW"
    session.flush()


def watch_event_for_document(
    session: Session,
    document: DocumentVersion,
) -> StatusEvent | None:
    item = session.get(SourceItem, document.source_item_id)
    identity = _source_item_page_identity(item) if item is not None else None
    if identity is None:
        return None
    watch = session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.host == identity[0])
    )
    if watch is None or watch.current_event_id is None:
        return None
    event = session.get(StatusEvent, watch.current_event_id)
    if event is None or event.archived_at is not None or event.merged_into_id is not None:
        return None
    return event


def resolve_watch_event(session: Session, watch: StatusMatchWatch) -> StatusEvent | None:
    if watch.current_event_id is not None:
        return session.get(StatusEvent, watch.current_event_id)
    document_ids = [document.id for document in current_watch_documents(session, watch)]
    if not document_ids:
        return None
    event_ids = set(
        session.scalars(
            select(EventEvidence.event_id).where(
                EventEvidence.document_version_id.in_(document_ids)
            )
        )
    )
    active_events = [
        event
        for event_id in event_ids
        if (event := session.get(StatusEvent, event_id)) is not None
        and event.archived_at is None
        and event.merged_into_id is None
    ]
    if len(active_events) == 1:
        watch.current_event_id = active_events[0].id
        session.flush()
        return active_events[0]
    return None


def delete_watch_only(session: Session, watch: StatusMatchWatch) -> None:
    for page in session.scalars(
        select(StatusMatchWatchPage).where(StatusMatchWatchPage.watch_id == watch.id)
    ):
        session.delete(page)
    session.delete(watch)
    session.flush()


def _watch_page(
    session: Session,
    watch_id: UUID,
    page_kind: str,
) -> StatusMatchWatchPage:
    page = session.scalar(
        select(StatusMatchWatchPage).where(
            StatusMatchWatchPage.watch_id == watch_id,
            StatusMatchWatchPage.page_kind == page_kind,
        )
    )
    if page is None:
        raise LookupError("StatusMatch watch page was not found")
    return page


def _watch_has_both_documents(session: Session, watch_id: UUID) -> bool:
    pages = list(
        session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch_id
            )
        )
    )
    return (
        {page.page_kind for page in pages} == {"activity", "faq"}
        and all(page.current_document_version_id is not None for page in pages)
    )


def _watch_error(session: Session, watch_id: UUID) -> str | None:
    return next(
        (
            page.last_error
            for page in session.scalars(
                select(StatusMatchWatchPage).where(
                    StatusMatchWatchPage.watch_id == watch_id
                )
            )
            if page.last_error
        ),
        None,
    )


def _source_item_page_identity(item: SourceItem) -> tuple[str, str] | None:
    if item.source_id != MAIL_SOURCE_ID or not item.external_id.startswith(
        PAGE_EXTERNAL_ID_PREFIX
    ):
        return None
    remainder = item.external_id[len(PAGE_EXTERNAL_ID_PREFIX) :]
    try:
        host, page_kind = remainder.rsplit(":", 1)
    except ValueError:
        return None
    if not is_project_statusmatch_host(host) or page_kind not in {"activity", "faq"}:
        return None
    return host, page_kind
