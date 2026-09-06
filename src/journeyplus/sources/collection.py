from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.service import IngestionService
from journeyplus.contracts import RunStatus
from journeyplus.models import CollectionRun, Source, SourceAutomationState
from journeyplus.sources.base import SourceAdapter
from journeyplus.statusmatch.service import finalize_statusmatch_watch
from journeyplus.statusmatch.watchlist import (
    ensure_statusmatch_watch,
    record_statusmatch_page_error,
    record_statusmatch_page_result,
    statusmatch_page_identity,
    successful_gmail_message_ids,
    watched_statusmatch_hosts,
)


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    run_id: str
    source_id: str
    discovered: int
    considered: int
    new_versions: int
    document_version_ids: tuple[str, ...] = ()
    current_document_version_ids: tuple[str, ...] = ()
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
        source_state: SourceAutomationState | None = None
        configure_feed_incremental = getattr(
            adapter, "configure_feed_incremental_discovery", None
        )
        if callable(configure_feed_incremental):
            source_state = _source_automation_state(session, adapter.source_id)
            configure_feed_incremental(
                discovery_cursor=source_state.discovery_cursor
            )
        configure_incremental = getattr(
            adapter, "configure_incremental_discovery", None
        )
        if callable(configure_incremental):
            source_state = _source_automation_state(session, adapter.source_id)
            configure_incremental(
                successful_message_ids=successful_gmail_message_ids(session),
                watched_hosts=watched_statusmatch_hosts(session),
                discovery_cursor=source_state.discovery_cursor,
            )
        discovered_items = adapter.discover()
        items = (
            discovered_items[:max_items]
            if max_items is not None
            else discovered_items
        )
        fully_considered = len(items) == len(discovered_items)
        if (
            not fully_considered
            and getattr(adapter, "requires_complete_cursor_batch", False)
        ):
            raise RuntimeError(
                "Incremental cursor batch exceeds max_items; increase the source "
                "item limit so the cursor can advance without dropping discoveries"
            )
        ingestion = IngestionService(session)
        reparsed = ingestion.reparse_outdated_snapshots(
            source_id=adapter.source_id
        )
        document_version_ids: list[str] = [
            str(result.document_version.id) for result in reparsed
        ]
        current_document_version_ids: list[str] = [
            str(result.document_version.id) for result in reparsed
        ]
        touched_statusmatch_hosts: set[str] = set()
        for item in items:
            managed_page = item.raw_metadata.get("managed_statusmatch_snapshot") is True
            if managed_page:
                host, _ = statusmatch_page_identity(item)
                ensure_statusmatch_watch(session, host)
                touched_statusmatch_hosts.add(host)
            try:
                if not ingestion.should_fetch(item):
                    current = ingestion.current_document(item)
                    if current is not None:
                        current_document_version_ids.append(str(current.id))
                    continue
                result = ingestion.ingest(item, adapter.fetch(item))
            except Exception as exc:
                if not managed_page:
                    raise
                record_statusmatch_page_error(
                    session,
                    item=item,
                    error=exc,
                )
                continue
            if managed_page:
                record_statusmatch_page_result(
                    session,
                    item=item,
                    result=result,
                )
            current_document_version_ids.append(str(result.document_version.id))
            if result.new_version:
                document_version_ids.append(str(result.document_version.id))
        for host in sorted(touched_statusmatch_hosts):
            finalize_statusmatch_watch(session, host)
        cursor_after_collection = getattr(
            adapter, "discovery_cursor_after_collection", None
        )
        if callable(cursor_after_collection):
            source_state = source_state or _source_automation_state(
                session, adapter.source_id
            )
            next_cursor = cursor_after_collection(
                considered_items=items,
                fully_considered=fully_considered,
            )
            if next_cursor is not None:
                source_state.discovery_cursor = next_cursor
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
            tuple(dict.fromkeys(current_document_version_ids)),
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


def _source_automation_state(
    session: Session, source_id: str
) -> SourceAutomationState:
    state = session.get(SourceAutomationState, source_id)
    if state is None:
        state = SourceAutomationState(source_id=source_id)
        session.add(state)
        session.flush()
    return state


def collect_in_phases(factory, adapter, *, idempotency_key, max_items=None):
    """Discover/fetch without a DB session, then atomically ingest and advance cursor."""
    from copy import deepcopy
    if max_items is not None and max_items < 1:
        raise ValueError('max_items must be positive')
    idempotency_key = idempotency_key or f'manual:{adapter.source_id}:{uuid4()}'
    with factory.begin() as session:
        existing = session.scalar(select(CollectionRun).where(CollectionRun.idempotency_key == idempotency_key))
        if existing and existing.status == RunStatus.SUCCEEDED:
            return collect_manual(session, adapter, idempotency_key=idempotency_key, max_items=max_items)
        state = _source_automation_state(session, adapter.source_id)
        baseline_cursor = deepcopy(state.discovery_cursor)
        configure = getattr(adapter, 'configure_feed_incremental_discovery', None)
        if callable(configure):
            configure(discovery_cursor=deepcopy(baseline_cursor))
        configure = getattr(adapter, 'configure_incremental_discovery', None)
        if callable(configure):
            configure(successful_message_ids=successful_gmail_message_ids(session),
                      watched_hosts=watched_statusmatch_hosts(session), discovery_cursor=deepcopy(baseline_cursor))
    discovered = adapter.discover()
    items = discovered[:max_items] if max_items is not None else discovered
    if len(items) != len(discovered) and getattr(adapter, 'requires_complete_cursor_batch', False):
        raise RuntimeError('Incremental cursor batch exceeds max_items; increase the source item limit')
    with factory() as session:
        ingestion = IngestionService(session)
        required = [item for item in items if ingestion.should_fetch(item)]
    responses = {}
    def key(item):return item.source_id, item.external_id, item.canonical_url
    for item in required:
        try:responses[key(item)] = adapter.fetch(item)
        except Exception as exc:
            if item.raw_metadata.get('managed_statusmatch_snapshot') is not True:
                raise
            responses[key(item)] = exc

    class PreparedAdapter:
        source_id = adapter.source_id
        requires_complete_cursor_batch = getattr(adapter, 'requires_complete_cursor_batch', False)
        def discover(self):return discovered
        def fetch(self, item):
            value = responses[key(item)]  # No network fallback inside publication.
            if isinstance(value, Exception):raise value
            return value
        def discovery_cursor_after_collection(self, **kwargs):
            callback = getattr(adapter, 'discovery_cursor_after_collection', None)
            return callback(**kwargs) if callable(callback) else None

    with factory.begin() as session:
        state = session.scalar(select(SourceAutomationState).where(SourceAutomationState.source_id == adapter.source_id).with_for_update())
        if state.discovery_cursor != baseline_cursor:
            raise ValueError('Source cursor changed during collection; retry from current cursor')
        return collect_manual(session, PreparedAdapter(), idempotency_key=idempotency_key, max_items=max_items)
