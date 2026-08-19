from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.service import IngestionService
from journeyplus.contracts import RunStatus
from journeyplus.models import CollectionRun, Source
from journeyplus.sources.base import SourceAdapter


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    run_id: str
    source_id: str
    discovered: int
    considered: int
    new_versions: int
    document_version_ids: tuple[str, ...] = ()
    reused_run: bool = False


def collect_manual(
    session: Session,
    adapter: SourceAdapter,
    *,
    idempotency_key: str | None = None,
    max_items: int | None = None,
) -> CollectionSummary:
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be positive")
    key = idempotency_key or f"manual:{adapter.source_id}:{uuid4()}"
    existing = session.scalar(
        select(CollectionRun).where(CollectionRun.idempotency_key == key)
    )
    if existing and existing.status == RunStatus.SUCCEEDED:
        return CollectionSummary(
            str(existing.id),
            existing.source_id,
            existing.discovered_count,
            min(existing.discovered_count, max_items or existing.discovered_count),
            0,
            (),
            True,
        )
    run = existing or CollectionRun(
        source_id=adapter.source_id,
        idempotency_key=key,
        status=RunStatus.PENDING,
    )
    if existing is None:
        session.add(run)
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    session.flush()
    try:
        discovered_items = adapter.discover()
        items = (
            discovered_items[:max_items]
            if max_items is not None
            else discovered_items
        )
        ingestion = IngestionService(session)
        document_version_ids: list[str] = []
        for item in items:
            if not ingestion.should_fetch(item):
                continue
            result = ingestion.ingest(item, adapter.fetch(item))
            if result.new_version:
                document_version_ids.append(str(result.document_version.id))
        run.status = RunStatus.SUCCEEDED
        run.discovered_count = len(discovered_items)
        run.document_count = len(document_version_ids)
        run.finished_at = datetime.now(UTC)
        session.flush()
        return CollectionSummary(
            str(run.id),
            adapter.source_id,
            len(discovered_items),
            len(items),
            len(document_version_ids),
            tuple(document_version_ids),
        )
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise


def automatically_scheduled_source_ids(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(Source.id).where(
                Source.enabled.is_(True),
                Source.automatic_scheduling.is_(True),
                Source.collection_cadence.is_not(None),
            )
        )
    )
