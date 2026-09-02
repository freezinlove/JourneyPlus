from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from journeyplus.models import (
    BriefRecord,
    DocumentVersion,
    FactSetRecord,
    SourceItem,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import Fetcher
from journeyplus.sources.statusmatch_links import (
    StatusMatchProjectLink,
    extract_statusmatch_project_links,
)
from journeyplus.statusmatch.service import (
    StatusMatchMonitoringSummary,
    monitor_statusmatch_watches,
)
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch


MAIL_SOURCE_ID = "status_services_mail"
MANAGED_PAGE_PREFIX = "statusmatch-page:"
TERMINAL_ROUTE_STATUSES = {"OFFICIAL_CLOSED"}


@dataclass(frozen=True, slots=True)
class ArticleRouteDiscoverySummary:
    documents_scanned: int = 0
    linked_documents: int = 0
    routes_created: int = 0
    route_ids: tuple[str, ...] = ()
    project_hosts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArticleProjectPreparationSummary:
    hosts_considered: int = 0
    watches_created: int = 0
    hosts_fetched: tuple[str, ...] = ()
    monitoring: StatusMatchMonitoringSummary = StatusMatchMonitoringSummary()
    ready_routes: int = 0
    waiting_routes: int = 0
    closed_routes: int = 0


def third_party_statusmatch_links(
    session: Session,
    document: DocumentVersion,
) -> tuple[StatusMatchProjectLink, ...]:
    item = session.get(SourceItem, document.source_item_id)
    if item is None or not _eligible_third_party_item(item):
        return ()
    body = document.raw_body or document.normalized_body
    return extract_statusmatch_project_links(body, content_type=document.content_type)


def is_third_party_statusmatch_article(
    session: Session,
    document: DocumentVersion,
) -> bool:
    return bool(third_party_statusmatch_links(session, document))


def discover_statusmatch_article_routes(
    session: Session,
    *,
    source_ids: list[str] | tuple[str, ...] | None = None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
) -> ArticleRouteDiscoverySummary:
    documents = _candidate_documents(
        session,
        source_ids=source_ids,
        document_ids=document_ids,
    )
    linked_documents = 0
    created: list[str] = []
    hosts: set[str] = set()
    for document in documents:
        links = third_party_statusmatch_links(session, document)
        if not links:
            continue
        linked_documents += 1
        for link in links:
            hosts.add(link.host)
            route = session.scalar(
                select(StatusMatchArticleRoute).where(
                    StatusMatchArticleRoute.document_version_id == document.id,
                    StatusMatchArticleRoute.project_host == link.host,
                )
            )
            if route is not None:
                continue
            route = StatusMatchArticleRoute(
                document_version_id=document.id,
                project_host=link.host,
                project_url=link.canonical_url,
                status="DISCOVERED",
            )
            session.add(route)
            session.flush()
            created.append(str(route.id))
    return ArticleRouteDiscoverySummary(
        documents_scanned=len(documents),
        linked_documents=linked_documents,
        routes_created=len(created),
        route_ids=tuple(created),
        project_hosts=tuple(sorted(hosts)),
    )


def prepare_statusmatch_article_projects(
    session: Session,
    fetcher: Fetcher,
    *,
    hosts: list[str] | tuple[str, ...] | None = None,
    checked_at: datetime | None = None,
) -> ArticleProjectPreparationSummary:
    routes = _preparable_routes(session, hosts=hosts)
    route_hosts = sorted({route.project_host for route in routes})
    created = 0
    fetch_hosts: list[str] = []
    for host in route_hosts:
        watch = session.scalar(
            select(StatusMatchWatch).where(StatusMatchWatch.host == host)
        )
        if watch is None:
            watch = ensure_statusmatch_watch(session, host)
            created += 1
        if not _watch_has_complete_snapshot(session, watch):
            fetch_hosts.append(host)

    monitoring = StatusMatchMonitoringSummary()
    if fetch_hosts:
        monitoring = monitor_statusmatch_watches(
            session,
            fetcher,
            hosts=fetch_hosts,
            checked_at=checked_at or datetime.now(UTC),
        )
    ready, waiting, closed = refresh_statusmatch_article_route_readiness(
        session,
        hosts=route_hosts,
        fetched_hosts=set(fetch_hosts),
    )
    return ArticleProjectPreparationSummary(
        hosts_considered=len(route_hosts),
        watches_created=created,
        hosts_fetched=tuple(fetch_hosts),
        monitoring=monitoring,
        ready_routes=ready,
        waiting_routes=waiting,
        closed_routes=closed,
    )


def refresh_statusmatch_article_route_readiness(
    session: Session,
    *,
    hosts: list[str] | tuple[str, ...] | None = None,
    fetched_hosts: set[str] | None = None,
) -> tuple[int, int, int]:
    statement = select(StatusMatchArticleRoute).where(
        StatusMatchArticleRoute.event_id.is_(None),
        ~StatusMatchArticleRoute.status.in_(TERMINAL_ROUTE_STATUSES),
    )
    if hosts is not None:
        normalized = {host.casefold().rstrip(".") for host in hosts}
        statement = statement.where(StatusMatchArticleRoute.project_host.in_(normalized))
    routes = list(session.scalars(statement.order_by(StatusMatchArticleRoute.created_at)))
    ready = waiting = closed = 0
    fetched_hosts = fetched_hosts or set()
    for route in routes:
        watch = session.scalar(
            select(StatusMatchWatch).where(
                StatusMatchWatch.host == route.project_host
            )
        )
        if watch is None:
            if route.project_host in fetched_hosts:
                route.status = "OFFICIAL_CLOSED"
                route.last_error = None
                closed += 1
            else:
                route.status = "WAITING_OFFICIAL"
                waiting += 1
            continue
        event = (
            session.get(StatusEvent, watch.current_event_id)
            if watch.current_event_id is not None
            else None
        )
        if _event_has_current_official_output(session, event):
            assert event is not None
            route.event_id = event.id
            route.status = "READY"
            route.last_error = None
            ready += 1
        else:
            route.status = "WAITING_OFFICIAL"
            route.last_error = watch.last_error
            waiting += 1
    session.flush()
    return ready, waiting, closed


def pending_article_project_hosts(session: Session) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(
                session.scalars(
                    select(StatusMatchArticleRoute.project_host).where(
                        StatusMatchArticleRoute.event_id.is_(None),
                        ~StatusMatchArticleRoute.status.in_(TERMINAL_ROUTE_STATUSES),
                    )
                )
            )
        )
    )


def _eligible_third_party_item(item: SourceItem) -> bool:
    if item.source_id == MAIL_SOURCE_ID:
        return False
    if item.external_id.startswith(MANAGED_PAGE_PREFIX):
        return False
    return (item.raw_metadata or {}).get("managed_statusmatch_snapshot") is not True


def _candidate_documents(
    session: Session,
    *,
    source_ids: list[str] | tuple[str, ...] | None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None,
) -> list[DocumentVersion]:
    normalized_ids = (
        [UUID(str(value)) for value in document_ids]
        if document_ids is not None
        else None
    )
    if normalized_ids == []:
        return []
    statement = select(DocumentVersion).join(
        SourceItem, SourceItem.id == DocumentVersion.source_item_id
    )
    if source_ids is not None:
        statement = statement.where(SourceItem.source_id.in_(source_ids))
    if normalized_ids is not None:
        statement = statement.where(DocumentVersion.id.in_(normalized_ids))
    else:
        newer = aliased(DocumentVersion)
        latest_id = (
            select(newer.id)
            .where(newer.source_item_id == DocumentVersion.source_item_id)
            .order_by(newer.created_at.desc(), newer.id.desc())
            .limit(1)
            .correlate(DocumentVersion)
            .scalar_subquery()
        )
        statement = statement.where(DocumentVersion.id == latest_id)
    return list(
        session.scalars(
            statement.order_by(DocumentVersion.created_at, DocumentVersion.id)
        )
    )


def _preparable_routes(
    session: Session,
    *,
    hosts: list[str] | tuple[str, ...] | None,
) -> list[StatusMatchArticleRoute]:
    statement = select(StatusMatchArticleRoute).where(
        StatusMatchArticleRoute.event_id.is_(None),
        ~StatusMatchArticleRoute.status.in_(TERMINAL_ROUTE_STATUSES),
    )
    if hosts is not None:
        normalized = {host.casefold().rstrip(".") for host in hosts}
        statement = statement.where(StatusMatchArticleRoute.project_host.in_(normalized))
    return list(session.scalars(statement.order_by(StatusMatchArticleRoute.created_at)))


def _watch_has_complete_snapshot(session: Session, watch: StatusMatchWatch) -> bool:
    pages = list(
        session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    )
    return (
        watch.status == "ACTIVE"
        and {page.page_kind for page in pages} == {"activity", "faq", "terms"}
        and all(
            page.current_document_version_id is not None and page.last_error is None
            for page in pages
        )
    )


def _event_has_current_official_output(
    session: Session,
    event: StatusEvent | None,
) -> bool:
    if (
        event is None
        or event.archived_at is not None
        or event.merged_into_id is not None
        or event.current_fact_set_id is None
        or event.current_brief_id is None
    ):
        return False
    fact = session.get(FactSetRecord, event.current_fact_set_id)
    brief = session.get(BriefRecord, event.current_brief_id)
    return (
        fact is not None
        and brief is not None
        and brief.fact_set_id == fact.id
    )
