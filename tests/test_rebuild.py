from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from journeyplus.automation.rebuild import (
    DERIVED_RESET_CONFIRMATION,
    reset_membership_derived_data,
)
from journeyplus.models import (
    AnalysisRun,
    AutomationLease,
    BriefRecord,
    CollectionRun,
    DocumentVersion,
    EventEvidence,
    FactSetRecord,
    JobRun,
    Source,
    SourceItem,
    StatusEvent,
    StatusMatchWatch,
)
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch


def _seed_raw_and_derived(session_factory) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        session.add(
            Source(
                id="ffb_status_match_catalog",
                name="Retired FFB catalog",
                adapter_type="static_catalog",
                discovery_config={},
                access_policy={},
                collection_cadence=None,
                automatic_scheduling=False,
                enabled=False,
            )
        )
        session.flush()
        item = SourceItem(
            source_id="ffb_status_match_catalog",
            external_id="rebuild-item",
            discovered_url="https://example.com/catalog",
            canonical_url="https://example.com/catalog",
            title="Rebuild fixture",
            observed_at=datetime.now(UTC),
            raw_metadata={},
        )
        session.add(item)
        session.flush()
        document = DocumentVersion(
            source_item_id=item.id,
            canonical_url=item.canonical_url,
            raw_body="raw body",
            normalized_body="normalized body",
            content_type="text/plain",
            storage_mode="test",
            raw_hash="1" * 64,
            normalized_hash="2" * 64,
            parser_version="test",
            fetched_at=datetime.now(UTC),
        )
        collection = CollectionRun(
            source_id=item.source_id,
            idempotency_key="preserved-collection",
            status="SUCCEEDED",
        )
        session.add_all([document, collection])
        session.flush()
        event = StatusEvent(
            created_from_key="derived-event",
            program="Example",
            summary="Example match",
            search_text="Example match",
        )
        session.add(event)
        session.flush()
        watch = ensure_statusmatch_watch(session, "example.statusmatch.com")
        watch.current_event_id = event.id
        session.add(
            EventEvidence(
                event_id=event.id,
                document_version_id=document.id,
                hint_index=0,
                source_url=document.canonical_url,
                locator="match",
            )
        )
        fact = FactSetRecord(
            event_id=event.id,
            version=1,
            schema_version="3",
            facts={
                "schema_version": "3",
                "event_id": str(event.id),
                "what_happened": {"value": None, "evidence": []},
            },
        )
        session.add(fact)
        session.flush()
        session.add(
            BriefRecord(
                fact_set_id=fact.id,
                version=1,
                schema_version="1",
                content={"title": "derived"},
            )
        )
        session.add(
            AnalysisRun(
                idempotency_key="derived-analysis",
                document_version_id=document.id,
                event_id=event.id,
                stage="STATUS_RELEVANCE",
                status="SUCCEEDED",
                input_version="1",
                provider="test",
                model="test",
                model_config_version="test",
                prompt_version="test",
                schema_version="test",
                result={},
            )
        )
        session.add(
            JobRun(
                idempotency_key="derived-job",
                job_type="test",
                status="SUCCEEDED",
            )
        )


def test_reset_removes_only_rebuildable_derived_data(session_factory) -> None:
    _seed_raw_and_derived(session_factory)

    summary = reset_membership_derived_data(
        session_factory,
        confirmation=DERIVED_RESET_CONFIRMATION,
    )

    assert summary.deleted["status_events"] == 1
    assert summary.deleted["analysis_runs"] == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 7
        assert session.scalar(select(func.count()).select_from(SourceItem)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert session.scalar(select(func.count()).select_from(CollectionRun)) == 1
        assert session.scalar(select(func.count()).select_from(StatusEvent)) == 0
        assert session.scalar(select(func.count()).select_from(FactSetRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 0
        assert session.scalar(select(func.count()).select_from(JobRun)) == 0
        watch = session.scalar(select(StatusMatchWatch))
        assert watch is not None and watch.current_event_id is None


def test_reset_refuses_active_automation_or_missing_confirmation(
    session_factory,
) -> None:
    _seed_raw_and_derived(session_factory)
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        session.add(
            AutomationLease(
                name="daily-source-automation",
                owner_id="active-owner",
                acquired_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )

    with pytest.raises(ValueError, match="confirmation"):
        reset_membership_derived_data(session_factory, confirmation="wrong")
    with pytest.raises(RuntimeError, match="lease"):
        reset_membership_derived_data(
            session_factory,
            confirmation=DERIVED_RESET_CONFIRMATION,
            now=now,
        )
