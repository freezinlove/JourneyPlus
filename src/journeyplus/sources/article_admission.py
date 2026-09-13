"""Screen transient feed content; publish only confirmed status opportunities."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from journeyplus.article_pipeline.contracts import TitleScreenDecision
from journeyplus.article_pipeline.interpretation import ArticleInterpreter
from journeyplus.article_pipeline.screening import BatchTitleScreener
from journeyplus.content.cleaner import lightly_clean
from journeyplus.content.service import IngestionService
from journeyplus.contracts import DocumentLabel, RunStatus
from journeyplus.models import CollectionRun, JobRun, SourceAutomationState
from journeyplus.sources.statusmatch_links import extract_statusmatch_project_links


class AdmissionRetryRequired(RuntimeError):
    """No negative decision was made; leave this item before the cursor."""


def rejection_key(item) -> str:
    identity = [item.source_id, item.external_id, item.discovery_fingerprint]
    digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return f"article-admission:{digest}"


def remember_rejection(session, item, decision: str) -> None:
    key = rejection_key(item)
    record = session.scalar(select(JobRun).where(JobRun.idempotency_key == key))
    if record is None:
        session.add(JobRun(idempotency_key=key, job_type="article_admission",
                          status=RunStatus.SUCCEEDED, attempts=1,
                          result={"decision": decision}, finished_at=datetime.now(UTC)))


class _CountedProvider:
    def __init__(self, provider):
        self.provider = provider
        self.metadata = provider.metadata
        self.calls = 0

    def generate_structured(self, **kwargs):
        before = getattr(self.provider, "calls", None)
        try:
            return self.provider.generate_structured(**kwargs)
        finally:
            after = getattr(self.provider, "calls", None)
            # A refused budget request is not a model call.
            self.calls += after - before if isinstance(before, int) and isinstance(after, int) else 1


def collect_status_articles(factory, adapter, provider, *, idempotency_key,
                            max_items=None, title_drop_enabled=True):
    from journeyplus.sources.collection import CollectionSummary, _source_automation_state

    key = idempotency_key or f"manual:{adapter.source_id}:{uuid4()}"
    with factory.begin() as session:
        run = session.scalar(select(CollectionRun).where(CollectionRun.idempotency_key == key))
        if run and run.status == RunStatus.SUCCEEDED:
            return CollectionSummary(str(run.id), adapter.source_id, run.discovered_count,
                                     min(run.discovered_count, max_items or run.discovered_count),
                                     0, reused_run=True)
        state = _source_automation_state(session, adapter.source_id)
        baseline_cursor = state.discovery_cursor
        configure = getattr(adapter, "configure_feed_incremental_discovery", None)
        if callable(configure):
            configure(discovery_cursor=baseline_cursor)
        if run is None:
            run = CollectionRun(source_id=adapter.source_id, idempotency_key=key)
            session.add(run)
        run.status = RunStatus.RUNNING
        run.error = None
        run.started_at = datetime.now(UTC)
        session.flush()
        run_id = run.id

    title_provider = _CountedProvider(provider)
    body_provider = _CountedProvider(provider)
    screener = BatchTitleScreener(None, title_provider)
    new_ids, current_ids = [], []
    title_dropped = body_dropped = 0

    def checkpoint(session, considered, *, complete):
        state = session.scalar(select(SourceAutomationState).where(
            SourceAutomationState.source_id == adapter.source_id).with_for_update())
        if state.discovery_cursor != baseline_cursor:
            raise AdmissionRetryRequired("Source cursor changed during article admission")
        callback = getattr(adapter, "discovery_cursor_after_collection", None)
        next_cursor = callback(considered_items=considered, fully_considered=complete) if callable(callback) else None
        if next_cursor is not None:
            state.discovery_cursor = next_cursor
        return state.discovery_cursor

    try:
        discovered = adapter.discover()
        items = discovered[:max_items] if max_items is not None else discovered
        if len(items) < len(discovered) and getattr(adapter, "requires_complete_cursor_batch", False):
            raise AdmissionRetryRequired("Source item limit cannot split this cursor batch")
        with factory.begin() as session:
            session.get(CollectionRun, run_id).discovered_count = len(discovered)

        for start in range(0, len(items), screener._batch_size):
            chunk = items[start:start + screener._batch_size]
            pending, skip = [], {}
            linked = {
                offset for offset, item in enumerate(chunk)
                if extract_statusmatch_project_links(
                    str(item.raw_metadata.get("feed_body") or item.raw_metadata.get("feed_summary") or ""),
                    content_type="text/html",
                )
            }
            with factory() as session:
                ingestion = IngestionService(session)
                for offset, item in enumerate(chunk):
                    marker = session.scalar(select(JobRun).where(
                        JobRun.idempotency_key == rejection_key(item), JobRun.status == RunStatus.SUCCEEDED))
                    if marker and offset not in linked:
                        skip[offset] = None
                    elif not ingestion.should_fetch(item):
                        doc = ingestion.current_document(item)
                        skip[offset] = str(doc.id) if doc else None
                    elif offset not in linked:
                        pending.append((SimpleNamespace(id=uuid4()), item, offset))
            screens, title_error = screener.render_chunk(pending) if pending else ({}, None)
            by_offset = {offset: screens[doc.id] for doc, _, offset in pending}
            for offset, item in enumerate(chunk):
                position = start + offset
                complete = position + 1 == len(discovered)
                screen = by_offset.get(offset)
                interpretation = raw = None
                new_version = False
                if offset not in skip and (offset in linked or not (screen.decision == TitleScreenDecision.DROP and title_drop_enabled)):
                    raw = adapter.fetch(item)
                    if extract_statusmatch_project_links(raw.body, content_type=raw.content_type):
                        linked.add(offset)
                    else:
                        # A link disappearing between discovery and fetch needs a retry,
                        # not unconditional publication based on the earlier feed body.
                        if offset in linked:
                            raise AdmissionRetryRequired("StatusMatch project link changed during fetch")
                        cleaned = lightly_clean(raw)
                        document = SimpleNamespace(canonical_url=raw.canonical_url,
                                                   normalized_body=cleaned.normalized_body)
                        interpretation, _error = ArticleInterpreter(None, body_provider).render(document, item)
                        if interpretation is None or interpretation.label == DocumentLabel.UNCERTAIN:
                            raise AdmissionRetryRequired("Article interpretation failed or remains uncertain; retry required")
                with factory.begin() as session:
                    # The cursor lock also serializes concurrent publication of this item.
                    next_cursor = checkpoint(session, items[:position + 1], complete=complete)
                    if offset in skip:
                        if skip[offset]:
                            current_ids.append(skip[offset])
                    elif interpretation is None and offset not in linked:
                        remember_rejection(session, item, "TITLE_DROP")
                        title_dropped += 1
                    elif interpretation is not None and interpretation.label == DocumentLabel.NONE:
                        remember_rejection(session, item, "BODY_NONE")
                        body_dropped += 1
                    else:
                        if offset in linked:
                            marker = session.scalar(select(JobRun).where(
                                JobRun.idempotency_key == rejection_key(item)))
                            if marker is not None:
                                session.delete(marker)
                        ingested = IngestionService(session).ingest(item, raw)
                        doc = ingested.document_version
                        if offset not in linked:
                            stored_screen = screen.model_copy(update={"document_version_id": doc.id})
                            BatchTitleScreener(session, title_provider).screen(
                                [doc], rendered={doc.id: (stored_screen, title_error)})
                            ArticleInterpreter(session, body_provider).interpret(
                                doc, rendered=(interpretation, None))
                        current_ids.append(str(doc.id))
                        new_version = ingested.new_version
                        if new_version:
                            new_ids.append(str(doc.id))
                    session.get(CollectionRun, run_id).document_count += int(new_version)
                baseline_cursor = next_cursor
        with factory.begin() as session:
            checkpoint(session, items, complete=len(items) == len(discovered))
            run = session.get(CollectionRun, run_id)
            run.status = RunStatus.SUCCEEDED
            run.finished_at = datetime.now(UTC)
        return CollectionSummary(str(run_id), adapter.source_id, len(discovered), len(items),
                                 len(new_ids), tuple(new_ids), tuple(dict.fromkeys(current_ids)),
                                 title_dropped=title_dropped, body_dropped=body_dropped,
                                 title_model_calls=title_provider.calls,
                                 interpretation_model_calls=body_provider.calls)
    except Exception as exc:
        exc.admission_title_model_calls = title_provider.calls
        exc.admission_interpretation_model_calls = body_provider.calls
        with factory.begin() as session:
            run = session.get(CollectionRun, run_id)
            run.status = RunStatus.FAILED
            run.error = "Article admission incomplete; retry from the last completed item"
            run.finished_at = datetime.now(UTC)
        raise
