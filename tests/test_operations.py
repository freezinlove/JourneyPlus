from __future__ import annotations

from sqlalchemy import select

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import JobRun
from journeyplus.operations import (
    pending_documents,
    process_pending_documents,
    workflow_idempotency_key,
)
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources


class TwoDocumentAdapter:
    source_id = "ffb_elite_status_feed"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=f"document-{index}",
                discovered_url=f"https://example.com/document-{index}",
                canonical_url=f"https://example.com/document-{index}",
                title=f"Document {index}",
            )
            for index in range(2)
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=f"<article>{item.title}: ordinary points news</article>",
        )


class VersionedDocumentAdapter:
    source_id = "ffb_elite_status_feed"

    def __init__(self) -> None:
        self.body = "Version one"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="versioned-document",
                discovered_url="https://example.com/versioned-document",
                canonical_url="https://example.com/versioned-document",
                title="Versioned document",
                discovery_fingerprint=self.body,
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=self.body,
            content_type="text/plain",
        )


class StatusMailAndManagedPageAdapter:
    source_id = "status_services_mail"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="gmail-message-1",
                discovered_url="https://mail.example/message-1",
                canonical_url="https://mail.example/message-1",
                title="StatusMatch discovery email",
            ),
            DiscoveredItem(
                source_id=self.source_id,
                external_id="statusmatch-page:example.statusmatch.com:activity",
                discovered_url="https://example.statusmatch.com/",
                canonical_url="https://example.statusmatch.com/",
                title="Managed StatusMatch page",
            ),
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=f"<article>{item.title}</article>",
        )


def _not_a_status_opportunity(reason: str) -> dict:
    return {
        "label": "NONE",
        "confidence": 0.99,
        "reason": reason,
        "event_hints": [],
    }


def test_managed_statusmatch_pages_are_excluded_but_mail_remains_pending(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collect_manual(session, StatusMailAndManagedPageAdapter())

    provider = SequenceAIProvider([])
    summary = process_pending_documents(
        session_factory,
        provider,
        source_id="status_services_mail",
        limit=10,
    )

    assert summary.selected == 1
    assert summary.succeeded == 1
    assert len(provider.calls) == 0
    with session_factory() as session:
        assert pending_documents(
            session,
            provider,
            source_id="status_services_mail",
            limit=10,
        ) == []


def test_pending_processing_is_limited_and_idempotent(session_factory) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collect_manual(session, TwoDocumentAdapter())

    provider = SequenceAIProvider(
        [
            _not_a_status_opportunity("first"),
            _not_a_status_opportunity("second"),
        ]
    )
    first = process_pending_documents(
        session_factory,
        provider,
        source_id="ffb_elite_status_feed",
        limit=1,
    )
    second = process_pending_documents(
        session_factory,
        provider,
        source_id="ffb_elite_status_feed",
        limit=10,
    )
    third = process_pending_documents(
        session_factory,
        provider,
        source_id="ffb_elite_status_feed",
        limit=10,
    )

    assert (first.selected, first.succeeded, first.failed) == (1, 1, 0)
    assert (second.selected, second.succeeded, second.failed) == (1, 1, 0)
    assert third.selected == 0
    assert len(provider.calls) == 2


class FailureIsolationProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="failure-isolation",
        region="local",
        config_version="failure-isolation-v1",
    )

    def generate_structured(
        self, *, system_prompt, user_prompt, output_model
    ):
        if output_model.__name__ == "RelevanceResult":
            if "Document 0" in user_prompt:
                payload = {
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
            else:
                payload = _not_a_status_opportunity("not a status opportunity")
            return output_model.model_validate(payload)
        raise RuntimeError("simulated downstream failure")


def test_one_document_failure_does_not_block_the_next_document(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collect_manual(session, TwoDocumentAdapter())

    summary = process_pending_documents(
        session_factory,
        FailureIsolationProvider(),
        source_id="ffb_elite_status_feed",
        limit=2,
    )

    assert summary.selected == 2
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert {item.error is None for item in summary.documents} == {True, False}
    with session_factory() as session:
        statuses = set(session.scalars(select(JobRun.status)))
    assert statuses == {"SUCCEEDED", "FAILED"}


def test_initialization_mode_stops_after_first_document_failure(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collect_manual(session, TwoDocumentAdapter())

    provider = FailureIsolationProvider()
    summary = process_pending_documents(
        session_factory,
        provider,
        source_id="ffb_elite_status_feed",
        limit=2,
        stop_on_failure=True,
    )

    assert summary.selected == 2
    assert summary.attempted == 1
    assert summary.failed == 1
    assert summary.succeeded == 0
    assert summary.stopped_early


def test_pending_processing_can_be_scoped_to_exact_document_ids(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collection = collect_manual(session, TwoDocumentAdapter())
    selected_id = collection.current_document_version_ids[1]
    provider = SequenceAIProvider([_not_a_status_opportunity("selected only")])

    summary = process_pending_documents(
        session_factory,
        provider,
        document_ids=[selected_id],
        limit=10,
    )

    assert summary.selected == 1
    assert summary.documents[0].document_version_id == selected_id
    with session_factory() as session:
        remaining = pending_documents(
            session,
            provider,
            source_id="ffb_elite_status_feed",
            limit=10,
        )
    assert len(remaining) == 1
    assert str(remaining[0][0]) != selected_id


def test_global_pending_selection_uses_only_latest_document_version(
    session_factory,
) -> None:
    adapter = VersionedDocumentAdapter()
    with session_factory.begin() as session:
        seed_sources(session)
        first = collect_manual(session, adapter, idempotency_key="version:first")
        adapter.body = "Version two"
        second = collect_manual(session, adapter, idempotency_key="version:second")

    with session_factory() as session:
        pending = pending_documents(
            session,
            SequenceAIProvider([]),
            source_id="ffb_elite_status_feed",
            limit=10,
        )

    assert len(pending) == 1
    assert str(pending[0][0]) == second.current_document_version_ids[0]
    assert str(pending[0][0]) != first.current_document_version_ids[0]


def test_workflow_idempotency_changes_when_any_stage_version_changes(
    session_factory, monkeypatch
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        collection = collect_manual(session, TwoDocumentAdapter(), max_items=1)
    document_id = collection.current_document_version_ids[0]
    provider = SequenceAIProvider([])
    original = workflow_idempotency_key(document_id, provider)

    monkeypatch.setattr("journeyplus.operations.FACT_PROMPT_VERSION", "facts-next")
    changed = workflow_idempotency_key(document_id, provider)

    assert changed != original
