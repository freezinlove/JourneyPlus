from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage
from journeyplus.models import (
    AnalysisRun,
    BriefRecord,
    FactSetRecord,
    StatusEvent,
    StatusMatchChangeSet,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import Fetcher, HttpxFetcher
from journeyplus.statusmatch.project_workflow import (
    process_pending_statusmatch_projects,
)
from journeyplus.statusmatch.service import monitor_statusmatch_watches
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch


def audit_statusmatch_projects(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    hosts: list[str] | tuple[str, ...],
    refresh: bool = True,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    normalized_hosts = list(
        dict.fromkeys(host.casefold().rstrip(".") for host in hosts)
    )
    if not normalized_hosts:
        raise ValueError("At least one StatusMatch host is required")
    with session_factory() as session:
        analysis_run_ids_before = set(session.scalars(select(AnalysisRun.id)))
    with session_factory.begin() as session:
        for host in normalized_hosts:
            ensure_statusmatch_watch(session, host)
    monitoring: dict[str, Any] | None = None
    if refresh:
        with session_factory.begin() as session:
            monitoring = asdict(
                monitor_statusmatch_watches(
                    session,
                    fetcher or HttpxFetcher(),
                    hosts=normalized_hosts,
                )
            )
    processing = process_pending_statusmatch_projects(
        session_factory,
        provider,
        hosts=normalized_hosts,
        limit=len(normalized_hosts),
    )
    with session_factory() as session:
        new_analysis_run_ids = set(session.scalars(select(AnalysisRun.id))) - (
            analysis_run_ids_before
        )
        projects = [
            _project_audit(session, host, new_analysis_run_ids)
            for host in normalized_hosts
        ]
    return {
        "hosts": normalized_hosts,
        "monitoring": monitoring,
        "processing": asdict(processing),
        "projects": projects,
        "assertions": {
            "classification_or_relationship_runs": sum(
                item.get("classification_or_relationship_runs", 0)
                for item in projects
            ),
            "dedicated_project_runs": sum(
                item.get("dedicated_project_runs", 0) for item in projects
            ),
            "brief_runs": sum(item.get("brief_runs", 0) for item in projects),
            "one_live_event_per_watch": all(
                item.get("event") is not None for item in projects
                if item.get("watch_status") == "ACTIVE"
            ),
        },
    }


def _project_audit(
    session: Session,
    host: str,
    new_analysis_run_ids: set,
) -> dict[str, Any]:
    watch = session.scalar(
        select(StatusMatchWatch).where(StatusMatchWatch.host == host)
    )
    if watch is None:
        return {
            "host": host,
            "watch_status": "ARCHIVED_OR_ABSENT",
            "error": "No live watch remains after refresh",
        }
    pages = list(
        session.scalars(
            select(StatusMatchWatchPage)
            .where(StatusMatchWatchPage.watch_id == watch.id)
            .order_by(StatusMatchWatchPage.page_kind.asc())
        )
    )
    event = (
        session.get(StatusEvent, watch.current_event_id)
        if watch.current_event_id is not None
        else None
    )
    fact_record = (
        session.get(FactSetRecord, event.current_fact_set_id)
        if event is not None and event.current_fact_set_id is not None
        else None
    )
    brief_record = (
        session.get(BriefRecord, event.current_brief_id)
        if event is not None and event.current_brief_id is not None
        else None
    )
    change_set = (
        session.scalar(
            select(StatusMatchChangeSet)
            .where(
                StatusMatchChangeSet.event_id == event.id,
                StatusMatchChangeSet.to_fact_set_id == fact_record.id,
            )
            .order_by(StatusMatchChangeSet.created_at.desc())
            .limit(1)
        )
        if event is not None and fact_record is not None
        else None
    )
    stages = (
        list(
            session.scalars(
                select(AnalysisRun.stage).where(AnalysisRun.event_id == event.id)
            )
        )
        if event is not None
        else []
    )
    page_ids = {
        page.current_document_version_id
        for page in pages
        if page.current_document_version_id is not None
    }
    new_runs = list(
        session.scalars(
            select(AnalysisRun).where(
                AnalysisRun.id.in_(new_analysis_run_ids),
                (
                    (AnalysisRun.event_id == event.id)
                    if event is not None
                    else AnalysisRun.document_version_id.in_(page_ids)
                ),
            )
        )
    ) if new_analysis_run_ids else []
    new_page_classification_runs = list(
        session.scalars(
            select(AnalysisRun).where(
                AnalysisRun.id.in_(new_analysis_run_ids),
                AnalysisRun.document_version_id.in_(page_ids),
                AnalysisRun.stage.in_(
                    (
                        AnalysisStage.STATUS_RELEVANCE,
                        AnalysisStage.EVENT_RELATIONSHIP,
                    )
                ),
            )
        )
    ) if new_analysis_run_ids and page_ids else []
    new_stages = [run.stage for run in new_runs]
    facts = fact_record.facts if fact_record is not None else None
    return {
        "host": host,
        "watch_id": str(watch.id),
        "watch_status": watch.status,
        "watch_error": watch.last_error,
        "pages": [
            {
                "kind": page.page_kind,
                "url": page.canonical_url,
                "document_version_id": (
                    str(page.current_document_version_id)
                    if page.current_document_version_id is not None
                    else None
                ),
                "last_error": page.last_error,
            }
            for page in pages
        ],
        "event": (
            {
                "id": str(event.id),
                "program": event.program,
                "target_status": event.target_status,
                "summary": event.summary,
                "lifecycle_status": event.lifecycle_status,
                "archived_at": (
                    event.archived_at.isoformat()
                    if event.archived_at is not None
                    else None
                ),
            }
            if event is not None
            else None
        ),
        "fact_set": (
            {
                "id": str(fact_record.id),
                "version": fact_record.version,
                "has_conflicts": fact_record.has_conflicts,
                "mapping_count": len(facts.get("status_mappings", [])),
                "facts": facts,
            }
            if fact_record is not None and facts is not None
            else None
        ),
        "change_set": (
            {
                "id": str(change_set.id),
                "kind": change_set.kind,
                "changes": change_set.changes,
                "from_fact_set_id": (
                    str(change_set.from_fact_set_id)
                    if change_set.from_fact_set_id is not None
                    else None
                ),
                "to_fact_set_id": str(change_set.to_fact_set_id),
            }
            if change_set is not None
            else None
        ),
        "brief": (
            {
                "id": str(brief_record.id),
                "version": brief_record.version,
                "content": brief_record.content,
            }
            if brief_record is not None
            else None
        ),
        "analysis_stages": stages,
        "new_analysis_stages": new_stages,
        "classification_or_relationship_runs": len(
            new_page_classification_runs
        ),
        "dedicated_project_runs": new_stages.count(
            AnalysisStage.STATUSMATCH_PROJECT_EXTRACTION
        ),
        "brief_runs": new_stages.count(AnalysisStage.BRIEF_GENERATION),
        "historical_dedicated_project_runs": stages.count(
            AnalysisStage.STATUSMATCH_PROJECT_EXTRACTION
        ),
        "historical_brief_runs": stages.count(AnalysisStage.BRIEF_GENERATION),
    }
