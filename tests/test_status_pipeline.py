from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.clustering.relationship import EventRelationshipAnalyzer
from journeyplus.clustering.retrieval import CandidateRetriever
from journeyplus.contracts import (
    DocumentLabel,
    EventHint,
    OpportunityType,
    RelationshipType,
)
from journeyplus.models import (
    AnalysisRun,
    DocumentVersion,
    EventEvidence,
    EventRevision,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources
from journeyplus.status_topic.analyzer import StatusRelevanceAnalyzer
from journeyplus.status_topic.pipeline import StatusOpportunityPipeline


def _document(db_session, *, suffix: str, body: str, duplicate_of=None):
    seed_sources(db_session)
    item = SourceItem(
        source_id="ffb_elite_status_feed",
        external_id=f"item-{suffix}",
        discovered_url=f"https://example.com/{suffix}",
        canonical_url=f"https://example.com/{suffix}",
        title=f"Item {suffix}",
        observed_at=datetime.now(UTC),
        raw_metadata={},
    )
    db_session.add(item)
    db_session.flush()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=item.canonical_url,
        raw_body=body,
        normalized_body=body,
        content_type="text/plain",
        storage_mode="test",
        raw_hash=(suffix[0] * 64)[:64],
        normalized_hash=(suffix[-1] * 64)[:64],
        parser_version="test-v1",
        fetched_at=datetime.now(UTC),
        duplicate_of_id=duplicate_of,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _status_opportunity(program="Example Air", summary="Match to Gold"):
    return {
        "label": "STATUS_OPPORTUNITY",
        "confidence": 0.95,
        "reason": "direct status acquisition path",
        "event_hints": [
            {
                "program": program,
                "opportunity_type": "STATUS_MATCH",
                "summary": summary,
                "target_status": "Gold",
            }
        ],
    }


def test_none_and_invalid_classification_do_not_create_events(db_session) -> None:
    no_document = _document(db_session, suffix="n", body="Buy points with a bonus")
    no_provider = SequenceAIProvider(
        [
            {
                "label": "NONE",
                "confidence": 1,
                "reason": "no direct status result",
                "event_hints": [],
            }
        ]
    )
    no_result = StatusOpportunityPipeline(db_session, no_provider).process(no_document)
    assert no_result.relevance.result.label == DocumentLabel.NONE
    assert no_result.events == []

    invalid_document = _document(db_session, suffix="i", body="Ambiguous benefit")
    invalid_provider = SequenceAIProvider([ValueError("bad json"), ValueError("bad json")])
    invalid_result = StatusOpportunityPipeline(db_session, invalid_provider).process(
        invalid_document
    )
    assert invalid_result.relevance.result.label == DocumentLabel.UNCERTAIN
    assert invalid_result.relevance.run.status == "FAILED"
    assert invalid_result.events == []


def test_one_document_can_create_multiple_minimal_events_and_rerun_is_idempotent(
    db_session,
) -> None:
    document = _document(db_session, suffix="m", body="Two independent matches")
    response = _status_opportunity()
    response["event_hints"].append(
        {
            "program": "Example Hotel",
            "opportunity_type": "FAST_TRACK",
            "summary": "Fast track to Platinum",
            "target_status": "Platinum",
        }
    )
    provider = SequenceAIProvider([response])
    pipeline = StatusOpportunityPipeline(db_session, provider)
    first = pipeline.process(document)
    second = pipeline.process(document)

    assert len(first.events) == len(second.events) == 2
    assert {item.event.id for item in first.events} == {
        item.event.id for item in second.events
    }
    assert len(provider.calls) == 1
    assert db_session.scalar(select(func.count()).select_from(StatusEvent)) == 2
    assert db_session.scalar(select(func.count()).select_from(EventEvidence)) == 2
    assert db_session.scalar(select(func.count()).select_from(EventRevision)) == 2


def test_content_duplicate_reuses_relevance_analysis_without_model_call(db_session) -> None:
    first = _document(db_session, suffix="a", body="Same normalized content")
    first_provider = SequenceAIProvider([_status_opportunity()])
    first_analysis = StatusRelevanceAnalyzer(db_session, first_provider).analyze(first)
    second = _document(
        db_session,
        suffix="b",
        body="Same normalized content",
        duplicate_of=first.id,
    )
    second_provider = SequenceAIProvider([])
    second_analysis = StatusRelevanceAnalyzer(db_session, second_provider).analyze(second)

    assert first_analysis.result == second_analysis.result
    assert second_analysis.reused
    assert second_provider.calls == []
    assert db_session.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_sql_candidate_retrieval_and_relationship_update_are_separate(db_session) -> None:
    existing_document = _document(db_session, suffix="c", body="Initial match")
    existing_event = StatusOpportunityPipeline(
        db_session, SequenceAIProvider([_status_opportunity()])
    ).process(existing_document).events[0].event

    hint = EventHint(
        program="Example Air",
        opportunity_type=OpportunityType.STATUS_MATCH,
        summary="Deadline extended",
        target_status="Gold",
    )
    candidates = CandidateRetriever(db_session).retrieve(hint)
    assert existing_event.id in {item.id for item in candidates}

    new_document = _document(db_session, suffix="d", body="The deadline was extended")
    provider = SequenceAIProvider(
        [
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.92,
                "reason": "same program and offer, revised deadline",
                "candidate_event_id": str(existing_event.id),
            }
        ]
    )
    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=new_document,
        hint=hint,
        hint_index=0,
        candidates=candidates,
    )
    assert relationship.result.relationship == RelationshipType.UPDATE_OF
    assert relationship.run is not None
    assert relationship.run.stage == "EVENT_RELATIONSHIP"


def test_relationship_aggregation_handles_update_and_uncertain_without_duplicates(
    db_session,
) -> None:
    original_document = _document(db_session, suffix="f", body="Initial direct match")
    original_event = StatusOpportunityPipeline(
        db_session, SequenceAIProvider([_status_opportunity()])
    ).process(original_document).events[0].event

    update_document = _document(db_session, suffix="g", body="Match deadline extended")
    update_provider = SequenceAIProvider(
        [
            _status_opportunity(summary="Match deadline extended"),
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.95,
                "reason": "same offer with a revised deadline",
                "candidate_event_id": str(original_event.id),
            },
        ]
    )
    update_pipeline = StatusOpportunityPipeline(db_session, update_provider)
    updated = update_pipeline.process(update_document)
    rerun = update_pipeline.process(update_document)
    assert updated.events[0].event.id == rerun.events[0].event.id == original_event.id
    assert db_session.scalar(
        select(func.count()).select_from(EventRevision).where(
            EventRevision.event_id == original_event.id,
            EventRevision.relationship == "UPDATE_OF",
        )
    ) == 1

    uncertain_document = _document(db_session, suffix="h", body="Possibly a new match")
    uncertain_provider = SequenceAIProvider(
        [
            _status_opportunity(summary="Possibly a separate match"),
            {
                "relationship": "UNCERTAIN",
                "confidence": 0.4,
                "reason": "not enough terms to merge safely",
                "candidate_event_id": str(original_event.id),
            },
        ]
    )
    uncertain = StatusOpportunityPipeline(db_session, uncertain_provider).process(
        uncertain_document
    )
    assert uncertain.events[0].event.id != original_event.id
    assert uncertain.events[0].event.status == "NEEDS_REVIEW"
    assert uncertain.events[0].needs_review


def test_relevance_can_rerun_with_new_prompt_without_relationship_contract(db_session) -> None:
    document = _document(db_session, suffix="e", body="Direct match")
    provider = SequenceAIProvider(
        [_status_opportunity(), _status_opportunity()]
    )
    first = StatusRelevanceAnalyzer(
        db_session, provider, prompt_version="status-v1"
    ).analyze(document)
    second = StatusRelevanceAnalyzer(
        db_session, provider, prompt_version="status-v2"
    ).analyze(document)
    assert first.run.id != second.run.id
    assert first.run.stage == second.run.stage == "STATUS_RELEVANCE"
