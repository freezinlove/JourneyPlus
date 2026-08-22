from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from journeyplus.review.api import create_review_app
from journeyplus.review.service import ReviewService
from journeyplus.models import (
    DocumentVersion,
    EventEvidence,
    FactSetRecord,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources


def _event(db_session, *, documents: int = 1):
    seed_sources(db_session)
    event = StatusEvent(
        created_from_key=f"review-{uuid4()}",
        program="Example Air",
        target_status="Gold",
        summary="Match to Gold",
        search_text="Example Air match Gold",
        status="NEEDS_REVIEW",
    )
    db_session.add(event)
    db_session.flush()
    versions = []
    for index in range(documents):
        item = SourceItem(
            source_id="ffb_elite_status_feed",
            external_id=f"review-item-{uuid4()}",
            discovered_url=f"https://example.com/review/{uuid4()}",
            canonical_url=f"https://example.com/review/{uuid4()}",
            title="Review item",
            observed_at=datetime.now(UTC),
            raw_metadata={},
        )
        db_session.add(item)
        db_session.flush()
        document = DocumentVersion(
            source_item_id=item.id,
            canonical_url=item.canonical_url,
            raw_body="Match body",
            normalized_body="Match body",
            content_type="text/plain",
            storage_mode="test",
            raw_hash=f"{index + 21:064x}",
            normalized_hash=f"{index + 31:064x}",
            parser_version="test",
            fetched_at=datetime.now(UTC),
        )
        db_session.add(document)
        db_session.flush()
        db_session.add(
            EventEvidence(
                event_id=event.id,
                document_version_id=document.id,
                hint_index=index,
                source_url=document.canonical_url,
                locator="paragraph 1",
            )
        )
        versions.append(document)
    db_session.flush()
    return event, versions


def _conflicted_facts(event, document):
    evidence = {
        "document_version_id": str(document.id),
        "source_url": document.canonical_url,
        "locator": "paragraph 1",
    }
    return {
        "schema_version": "1",
        "event_id": str(event.id),
        "what_happened": {"value": "Match to Gold", "evidence": [evidence]},
        "cost": {
            "value": None,
            "evidence": [evidence],
            "conflict": True,
            "alternatives": ["99 USD", "149 USD"],
        },
        "eligibility": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "target_status": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "challenge_requirements": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "region": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "deadline": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "status_validity": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "action_link": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
        "caveats": {"value": None, "evidence": [], "conflict": False, "alternatives": []},
    }


def test_conflict_review_requires_resolution_and_preserves_old_fact_version(db_session) -> None:
    event, documents = _event(db_session)
    record = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version="1",
        facts=_conflicted_facts(event, documents[0]),
        has_conflicts=True,
    )
    db_session.add(record)
    db_session.flush()
    event.current_fact_set_id = record.id
    service = ReviewService(db_session)

    with pytest.raises(ValueError, match="conflicts"):
        service.confirm(event.id)
    result = service.confirm(
        event.id, conflict_resolutions={"cost": "99 USD"}, reason="checked terms"
    )
    current = db_session.get(FactSetRecord, event.current_fact_set_id)
    assert result.event.status == "CONFIRMED"
    assert current is not None and current.version == 2 and not current.has_conflicts
    assert db_session.get(FactSetRecord, record.id).has_conflicts


def test_split_then_merge_moves_evidence_and_invalidates_derived_outputs(db_session) -> None:
    event, documents = _event(db_session, documents=2)
    service = ReviewService(db_session)
    split = service.split(event.id, [documents[1].id], reason="different offer")
    created = split.created_event
    assert created is not None
    assert db_session.scalar(
        select(func.count()).select_from(EventEvidence).where(
            EventEvidence.event_id == created.id
        )
    ) == 1

    merged = service.merge(created.id, event.id, reason="same offer after review")
    assert merged.event.status == "MERGED"
    assert merged.event.merged_into_id == event.id
    assert db_session.scalar(
        select(func.count()).select_from(EventEvidence).where(
            EventEvidence.event_id == event.id
        )
    ) == 2
    assert event.current_fact_set_id is None and event.current_brief_id is None


def test_internal_review_api_exposes_queue_chain_and_actions(session_factory) -> None:
    with session_factory.begin() as session:
        event, _documents = _event(session)
        event_id = event.id
    client = TestClient(create_review_app(session_factory))

    queue = client.get("/internal/review/queue")
    assert queue.status_code == 200
    assert any(item["id"] == str(event_id) for item in queue.json())
    chain = client.get(f"/internal/review/events/{event_id}")
    assert chain.status_code == 200
    assert chain.json()["documents"][0]["normalized_body"] == "Match body"
    rejected = client.post(
        f"/internal/review/events/{event_id}/actions",
        json={"action": "REJECT", "reason": "not a public opportunity"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
