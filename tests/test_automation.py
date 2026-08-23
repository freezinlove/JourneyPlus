from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.automation.service import (
    AutomationLimits,
    acquire_automation_lease,
    automation_status,
    release_automation_lease,
    run_daily_cycle,
)
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import (
    AutomationRun,
    CollectionRun,
    DocumentVersion,
    Source,
    SourceAutomationState,
    StatusEvent,
)
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources


class SyntheticAdapter:
    def __init__(self, source_id: str, count: int = 1) -> None:
        self.source_id = source_id
        self._count = count

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=f"daily-{index}",
                discovered_url=f"https://example.com/daily-{index}",
                canonical_url=f"https://example.com/daily-{index}",
                title=f"Daily document {index}",
            )
            for index in range(self._count)
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=f"Ordinary points news {item.external_id}",
            content_type="text/plain",
        )


def _none(reason: str) -> dict:
    return {
        "label": "NONE",
        "confidence": 0.99,
        "reason": reason,
        "event_hints": [],
    }


def test_same_beijing_day_reuses_successful_source_run(session_factory) -> None:
    provider = SequenceAIProvider([_none("not a status opportunity")])
    now = datetime(2026, 8, 23, 2, tzinfo=UTC)

    first = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=now,
    )
    second = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=now + timedelta(hours=2),
    )

    assert first.status == "SUCCEEDED"
    assert first.documents_selected == first.documents_succeeded == 1
    assert second.status == "SUCCEEDED"
    assert second.sources[0].reused
    assert second.documents_selected == 0
    assert len(provider.calls) == 1
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(DocumentVersion)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(CollectionRun)
        ) == 1
        run = session.scalar(select(AutomationRun))
        assert run is not None and run.attempts == 2


def test_active_lease_skips_concurrent_trigger(session_factory) -> None:
    now = datetime(2026, 8, 23, 4, tzinfo=UTC)
    assert acquire_automation_lease(
        session_factory,
        owner_id="first-owner",
        now=now,
        lease_duration=timedelta(minutes=30),
    )

    result = run_daily_cycle(
        session_factory,
        SequenceAIProvider([]),
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=now + timedelta(minutes=1),
        owner_id="second-owner",
    )

    assert result.skipped
    assert result.status == "SKIPPED"
    assert result.skip_reason == "active database lease"
    release_automation_lease(
        session_factory, owner_id="first-owner", now=now + timedelta(minutes=2)
    )


def test_source_failure_is_isolated_and_lifecycle_still_advances(
    session_factory,
) -> None:
    now = datetime(2026, 8, 23, 6, tzinfo=UTC)
    with session_factory.begin() as session:
        seed_sources(session)
        event = StatusEvent(
            created_from_key="automation-expiring-event",
            program="Example Air",
            target_status="Gold",
            summary="Expired match",
            search_text="Example Air expired match",
            lifecycle_status="ACTIVE",
            application_deadline_at=now - timedelta(days=1),
        )
        session.add(event)

    def adapter_factory(source_id: str):
        if source_id == "status_services_mail":
            raise PermissionError("simulated Gmail refresh failure")
        return SyntheticAdapter(source_id)

    result = run_daily_cycle(
        session_factory,
        SequenceAIProvider([_none("ordinary news")]),
        adapter_factory,
        source_ids=["status_services_mail", "ffb_elite_status_feed"],
        now=now,
    )

    assert result.status == "FAILED"
    assert [item.status for item in result.sources] == ["FAILED", "SUCCEEDED"]
    assert result.documents_succeeded == 1
    assert result.lifecycle_expired == 1
    with session_factory() as session:
        failed = session.get(SourceAutomationState, "status_services_mail")
        succeeded = session.get(
            SourceAutomationState, "ffb_elite_status_feed"
        )
        event = session.scalar(
            select(StatusEvent).where(
                StatusEvent.created_from_key == "automation-expiring-event"
            )
        )
        assert failed is not None and failed.consecutive_failures == 1
        assert "PermissionError" in (failed.last_error or "")
        assert succeeded is not None and succeeded.consecutive_failures == 0
        assert event is not None and event.lifecycle_status == "EXPIRED"
        failed_collection = session.scalar(
            select(CollectionRun).where(
                CollectionRun.source_id == "status_services_mail"
            )
        )
        assert failed_collection is not None
        assert failed_collection.status == "FAILED"


def test_document_limit_leaves_visible_backlog(session_factory) -> None:
    provider = SequenceAIProvider(
        [_none("first document"), _none("second document")]
    )
    result = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id, count=2),
        source_ids=["ffb_elite_status_feed"],
        limits=AutomationLimits(
            source_items_per_source=10,
            documents=1,
            model_calls=10,
        ),
        now=datetime(2026, 8, 23, 8, tzinfo=UTC),
    )

    assert result.documents_selected == 1
    assert result.backlog_count == 1
    status = automation_status(session_factory, provider)
    assert status.backlog_count == 1
    source = next(
        item for item in status.sources if item.source_id == "ffb_elite_status_feed"
    )
    assert source.collection_cadence == "P1D"
    assert not source.automatic_scheduling
    assert source.pending_document_count == 1


def test_daily_cycle_only_processes_selected_sources(session_factory) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collect_manual(
            session,
            SyntheticAdapter("awardwallet_elite_status_feed"),
            idempotency_key="unselected-source-pending",
        )

    provider = SequenceAIProvider([_none("selected source document")])
    result = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=datetime(2026, 8, 24, 8, tzinfo=UTC),
    )

    assert result.documents_selected == result.documents_succeeded == 1
    assert result.backlog_count == 0
    assert len(provider.calls) == 1
    status = automation_status(session_factory, provider)
    assert status.backlog_count == 1
    awardwallet = next(
        item
        for item in status.sources
        if item.source_id == "awardwallet_elite_status_feed"
    )
    assert awardwallet.pending_document_count == 1


def test_automation_status_excludes_retired_source_backlog(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            Source(
                id="ffb_status_match_catalog",
                name="Retired FFB catalog",
                adapter_type="retired",
                discovery_config={},
                access_policy={},
                collection_cadence=None,
                automatic_scheduling=False,
                enabled=False,
            )
        )
        session.flush()
        collect_manual(
            session,
            SyntheticAdapter("ffb_status_match_catalog"),
            idempotency_key="retired-source-pending",
        )

    status = automation_status(session_factory, SequenceAIProvider([]))

    assert status.backlog_count == 0


def test_model_call_limit_stops_downstream_work_and_keeps_document_pending(
    session_factory,
) -> None:
    provider = SequenceAIProvider(
        [
            {
                "label": "STATUS_OPPORTUNITY",
                "confidence": 0.99,
                "reason": "direct status match",
                "event_hints": [
                    {
                        "program": "Example Air",
                        "summary": "Example Air status match",
                    }
                ],
            }
        ]
    )

    result = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        limits=AutomationLimits(
            source_items_per_source=10,
            documents=10,
            model_calls=1,
        ),
        now=datetime(2026, 8, 23, 10, tzinfo=UTC),
    )

    assert result.status == "FAILED"
    assert result.documents_selected == 1
    assert result.documents_failed == 1
    assert result.model_calls == 1
    assert result.backlog_count == 1


def test_failed_source_can_retry_same_day_and_resets_failure_state(
    session_factory,
) -> None:
    calls = 0

    def adapter_factory(source_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary feed failure")
        return SyntheticAdapter(source_id)

    provider = SequenceAIProvider([_none("ordinary news")])
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)
    failed = run_daily_cycle(
        session_factory,
        provider,
        adapter_factory,
        source_ids=["ffb_elite_status_feed"],
        now=now,
    )
    recovered = run_daily_cycle(
        session_factory,
        provider,
        adapter_factory,
        source_ids=["ffb_elite_status_feed"],
        now=now + timedelta(minutes=5),
    )

    assert failed.sources[0].status == "FAILED"
    assert recovered.sources[0].status == "SUCCEEDED"
    assert recovered.documents_succeeded == 1
    with session_factory() as session:
        state = session.get(SourceAutomationState, "ffb_elite_status_feed")
        run = session.scalar(select(CollectionRun))
        assert state is not None and state.consecutive_failures == 0
        assert state.last_error is None
        assert run is not None and run.status == "SUCCEEDED"
        assert session.scalar(
            select(func.count()).select_from(CollectionRun)
        ) == 1


def test_beijing_midnight_creates_a_new_day_bucket(session_factory) -> None:
    provider = SequenceAIProvider([_none("ordinary news")])
    before_midnight = datetime(2026, 8, 22, 15, 59, tzinfo=UTC)
    after_midnight = datetime(2026, 8, 22, 16, 1, tzinfo=UTC)

    first = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=before_midnight,
    )
    second = run_daily_cycle(
        session_factory,
        provider,
        lambda source_id: SyntheticAdapter(source_id),
        source_ids=["ffb_elite_status_feed"],
        now=after_midnight,
    )

    assert first.day_bucket == "2026-08-22"
    assert second.day_bucket == "2026-08-23"
    assert second.sources[0].reused is False
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(AutomationRun)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(CollectionRun)
        ) == 2
