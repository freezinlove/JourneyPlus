from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import Brief
from journeyplus.contracts import StatusMatchBrief, read_brief
from journeyplus.models import (
    BriefRecord,
    DocumentVersion,
    FactSetRecord,
    SourceItem,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchArticleSupplement,
    StatusMatchWatch,
)
from journeyplus.statusmatch.article_contracts import (
    ComposedStatusMatchBrief,
    StatusMatchSupplementView,
)


def composed_statusmatch_brief(
    session: Session,
    *,
    host: str | None = None,
    event_id: UUID | str | None = None,
) -> ComposedStatusMatchBrief:
    if (host is None) == (event_id is None):
        raise ValueError("exactly one of host or event_id is required")
    if host is not None:
        normalized_host = host.casefold().rstrip(".")
        watch = session.scalar(
            select(StatusMatchWatch).where(StatusMatchWatch.host == normalized_host)
        )
        if watch is None or watch.current_event_id is None:
            raise LookupError(f"No current StatusMatch project for {normalized_host}")
        event = session.get(StatusEvent, watch.current_event_id)
    else:
        event = session.get(StatusEvent, UUID(str(event_id)))
        if event is None:
            raise LookupError(f"StatusMatch event {event_id} was not found")
    if (
        event is None
        or event.current_fact_set_id is None
        or event.current_brief_id is None
    ):
        raise LookupError("StatusMatch event has no current official brief")
    fact = session.get(FactSetRecord, event.current_fact_set_id)
    brief = session.get(BriefRecord, event.current_brief_id)
    if fact is None or brief is None or brief.fact_set_id != fact.id:
        raise LookupError("StatusMatch official FactSet/Brief is incomplete")

    routes = _latest_routes_for_event(session, event.id)
    supplements = _current_supplements(
        session,
        routes=routes,
        fact_set_id=fact.id,
        brief_id=brief.id,
    )
    supplement_by_route = {supplement.route_id: supplement for supplement in supplements}
    supplement_views: list[StatusMatchSupplementView] = []
    for route in routes:
        document, item = _route_material(session, route)
        supplement = supplement_by_route.get(route.id)
        if supplement is not None:
            highlights = _highlight_texts(supplement.highlights)
            if not highlights:
                continue
            supplement_views.append(
                StatusMatchSupplementView(
                    article_title=item.title,
                    article_url=item.canonical_url,
                    article_published_at=item.published_at,
                    highlights=highlights,
                )
            )
    brief_payload = read_brief(brief.content)
    return ComposedStatusMatchBrief(
        title=brief_payload.title,
        summary=brief_payload.summary,
        key_points=[point.text for point in getattr(brief_payload, "key_points", [])],
        caveats=[point.text for point in getattr(brief_payload, "caveats", [])],
        source_links=brief_payload.source_links,
        supplements=supplement_views,
    )


def _highlight_texts(value: list[object]) -> list[str]:
    """Read current strings and legacy highlight objects without exposing metadata."""
    highlights: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("text")
        else:
            text = None
        if isinstance(text, str) and (normalized := " ".join(text.split())):
            highlights.append(normalized)
    return highlights


def _latest_routes_for_event(
    session: Session,
    event_id: UUID,
) -> list[StatusMatchArticleRoute]:
    routes = list(
        session.scalars(
            select(StatusMatchArticleRoute)
            .where(StatusMatchArticleRoute.event_id == event_id)
            .order_by(StatusMatchArticleRoute.created_at.desc())
        )
    )
    latest_by_item: dict[UUID, StatusMatchArticleRoute] = {}
    for route in routes:
        document = session.get(DocumentVersion, route.document_version_id)
        if document is not None:
            latest_by_item.setdefault(document.source_item_id, route)
    return sorted(
        latest_by_item.values(),
        key=lambda route: (route.project_host, str(route.id)),
    )


def _current_supplements(
    session: Session,
    *,
    routes: list[StatusMatchArticleRoute],
    fact_set_id: UUID,
    brief_id: UUID,
) -> list[StatusMatchArticleSupplement]:
    if not routes:
        return []
    rows = list(
        session.scalars(
            select(StatusMatchArticleSupplement)
            .where(
                StatusMatchArticleSupplement.route_id.in_([route.id for route in routes]),
                StatusMatchArticleSupplement.fact_set_id == fact_set_id,
                StatusMatchArticleSupplement.brief_id == brief_id,
            )
            .order_by(StatusMatchArticleSupplement.created_at.desc())
        )
    )
    latest: dict[UUID, StatusMatchArticleSupplement] = {}
    for row in rows:
        latest.setdefault(row.route_id, row)
    return list(latest.values())


def _route_material(
    session: Session,
    route: StatusMatchArticleRoute,
) -> tuple[DocumentVersion, SourceItem]:
    document = session.get(DocumentVersion, route.document_version_id)
    if document is None:
        raise LookupError("StatusMatch article document was not found")
    item = session.get(SourceItem, document.source_item_id)
    if item is None:
        raise LookupError("StatusMatch article source item was not found")
    return document, item
