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
    new_versions: int


def collect_manual(
    session: Session,
    adapter: SourceAdapter,
    *,
    idempotency_key: str | None = None,
) -> CollectionSummary:
    key = idempotency_key or f"manual:{adapter.source_id}:{uuid4()}"
    existing = session.scalar(
        select(CollectionRun).where(CollectionRun.idempotency_key == key)
    )
    if existing and existing.status == RunStatus.SUCCEEDED:
        return CollectionSummary(
            str(existing.id),
            existing.source_id,
            existing.discovered_count,
            existing.document_count,
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
        items = adapter.discover()
        ingestion = IngestionService(session)
        new_versions = 0
        for item in items:
            result = ingestion.ingest(item, adapter.fetch(item))
            new_versions += int(result.new_version)
        run.status = RunStatus.SUCCEEDED
        run.discovered_count = len(items)
        run.document_count = new_versions
        run.finished_at = datetime.now(UTC)
        session.flush()
        return CollectionSummary(str(run.id), adapter.source_id, len(items), new_versions)
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

