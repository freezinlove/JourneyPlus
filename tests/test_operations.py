from __future__ import annotations

from sqlalchemy import select

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import JobRun
from journeyplus.operations import process_pending_documents
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


def _not_a_status_opportunity(reason: str) -> dict:
    return {
        "label": "NONE",
        "confidence": 0.99,
        "reason": reason,
        "event_hints": [],
    }


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
