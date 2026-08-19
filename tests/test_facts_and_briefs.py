from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.briefs.service import BriefGenerator
from journeyplus.facts.service import FactConsolidator
from journeyplus.models import (
    AnalysisRun,
    BriefRecord,
    DocumentVersion,
    EventEvidence,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources


def _event_with_documents(db_session, bodies: list[str]):
    seed_sources(db_session)
    event = StatusEvent(
        created_from_key=f"event-{uuid4()}",
        program="Example Air",
        opportunity_type="STATUS_MATCH",
        target_status="Gold",
        summary="Example Air match to Gold",
        search_text="Example Air status match Gold",
    )
    db_session.add(event)
    db_session.flush()
    documents = []
    for index, body in enumerate(bodies):
        item = SourceItem(
            source_id="ffb_elite_status_feed",
            external_id=f"fact-item-{uuid4()}",
            discovered_url=f"https://example.com/facts/{event.id}/{index}",
            canonical_url=f"https://example.com/facts/{event.id}/{index}",
            title="Facts",
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
            raw_hash=f"{index + 1:064x}",
            normalized_hash=f"{index + 11:064x}",
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
                locator="status match terms",
            )
        )
        documents.append(document)
    db_session.flush()
    return event, documents


def _evidence(document, locator="paragraph 2"):
    return {
        "document_version_id": str(document.id),
        "source_url": document.canonical_url,
        "locator": locator,
    }


def _fact_response(event, document, *, what="Example Air offers a match to Gold"):
    return {
        "schema_version": "1",
        "event_id": str(event.id),
        "what_happened": {"value": what, "evidence": [_evidence(document)]},
        "target_status": {"value": "Gold", "evidence": [_evidence(document)]},
        "deadline": {"value": "2026-12-31", "evidence": [_evidence(document)]},
        "action_link": {
            "value": "https://example.com/apply",
            "evidence": [_evidence(document)],
        },
    }


def test_fact_consolidation_preserves_unknowns_and_requires_associated_evidence(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["Original long body: match to Gold by December 31."]
    )
    provider = SequenceAIProvider([_fact_response(event, documents[0])])
    consolidator = FactConsolidator(db_session, provider)
    first = consolidator.consolidate(event)
    second = consolidator.consolidate(event)

    assert first.fact_set.deadline.value == "2026-12-31"
    assert first.fact_set.cost.value is None
    assert first.fact_set.deadline.evidence[0].document_version_id == documents[0].id
    assert second.reused
    assert len(provider.calls) == 1

    invalid = _fact_response(event, documents[0])
    invalid["deadline"]["evidence"][0]["document_version_id"] = str(uuid4())
    bad_provider = SequenceAIProvider([invalid, invalid])
    with pytest.raises(ValueError, match="evidence validation"):
        FactConsolidator(
            db_session, bad_provider, prompt_version="fact-invalid-test"
        ).consolidate(event)


def test_conflicting_facts_stay_explicit_and_enter_review(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Cost is 99", "Cost is 149"])
    response = _fact_response(event, documents[0])
    response["cost"] = {
        "value": None,
        "evidence": [_evidence(documents[0]), _evidence(documents[1])],
        "conflict": True,
        "alternatives": ["99 USD", "149 USD"],
    }
    result = FactConsolidator(db_session, SequenceAIProvider([response])).consolidate(event)
    assert result.fact_set.cost.conflict
    assert result.record.has_conflicts
    assert event.status == "NEEDS_REVIEW"


def test_brief_reads_only_fact_set_and_traces_every_claim(db_session) -> None:
    event, documents = _event_with_documents(
        db_session, ["ORIGINAL ARTICLE BODY SHOULD NEVER ENTER BRIEF PROMPT"]
    )
    facts = FactConsolidator(
        db_session, SequenceAIProvider([_fact_response(event, documents[0])])
    ).consolidate(event)
    response = {
        "schema_version": "1",
        "fact_set_id": str(facts.record.id),
        "title": "Example Air 开放金卡匹配",
        "title_fact_keys": ["what_happened", "target_status"],
        "summary": "符合条件的会员可申请匹配至金卡，当前资料列出的截止日为 2026 年 12 月 31 日。",
        "summary_fact_keys": ["what_happened", "target_status", "deadline"],
        "key_points": [
            {"text": "目标会籍：金卡。", "fact_keys": ["target_status"]},
            {"text": "申请入口见来源页面。", "fact_keys": ["action_link"]},
        ],
        "caveats": [],
        "source_links": [documents[0].canonical_url],
    }
    provider = SequenceAIProvider([response])
    generator = BriefGenerator(db_session, provider)
    generated = generator.generate(facts.record)
    repeated = generator.generate(facts.record)

    assert generated.brief.title.startswith("Example Air")
    assert repeated.reused and repeated.record.id == generated.record.id
    assert len(provider.calls) == 1
    assert "ORIGINAL ARTICLE BODY" not in provider.calls[0]["user_prompt"]
    assert db_session.scalar(select(func.count()).select_from(BriefRecord)) == 1
    assert event.current_brief_id == generated.record.id


def test_brief_rejects_unknown_claims_unsupported_links_and_long_copy(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Body"])
    long_fact = "这是来源中的长段落。" * 30
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider(
            [_fact_response(event, documents[0], what=long_fact)]
        ),
    ).consolidate(event)
    bad = {
        "schema_version": "1",
        "fact_set_id": str(facts.record.id),
        "title": "会籍机会",
        "title_fact_keys": ["what_happened"],
        "summary": long_fact[:180],
        "summary_fact_keys": ["what_happened"],
        "key_points": [
            {"text": "费用已知。", "fact_keys": ["cost"]},
        ],
        "caveats": [],
        "source_links": ["https://unsupported.example/"],
    }
    provider = SequenceAIProvider([bad, bad])
    with pytest.raises(ValueError, match="grounding validation"):
        BriefGenerator(db_session, provider).generate(facts.record)
    failed = db_session.scalar(
        select(AnalysisRun).where(AnalysisRun.stage == "BRIEF_GENERATION")
    )
    assert failed is not None and failed.status == "FAILED"
