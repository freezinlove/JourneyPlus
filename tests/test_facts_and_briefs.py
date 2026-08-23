from __future__ import annotations

import json
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
    EventRevision,
    FactSetRecord,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources


def _event_with_documents(db_session, bodies: list[str]):
    seed_sources(db_session)
    event = StatusEvent(
        created_from_key=f"event-{uuid4()}",
        program="Example Air",
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


def _add_document_evidence(
    db_session,
    event,
    body: str,
    *,
    locator: str,
    hint_index: int = 0,
    relationship: str | None = None,
    deadline_extension: bool = False,
):
    token = uuid4().hex
    item = SourceItem(
        source_id="ffb_elite_status_feed",
        external_id=f"added-{token}",
        discovered_url=f"https://example.com/added/{token}",
        canonical_url=f"https://example.com/added/{token}",
        title="Added facts",
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
        raw_hash=(token * 2)[:64],
        normalized_hash=(token[::-1] * 2)[:64],
        parser_version="test",
        fetched_at=datetime.now(UTC),
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=document.id,
            hint_index=hint_index,
            source_url=document.canonical_url,
            locator=locator,
        )
    )
    if relationship is not None:
        db_session.add(
            EventRevision(
                event_id=event.id,
                document_version_id=document.id,
                relationship=relationship,
                snapshot={
                    "hint": {"summary": locator},
                    "relationship": {
                        "relationship": relationship,
                        "deadline_extension": deadline_extension,
                    },
                },
            )
        )
    db_session.flush()
    return document


def _fact_response(event, document, *, what="Example Air offers a match to Gold"):
    return {
        "schema_version": "2",
        "event_id": str(event.id),
        "what_happened": {"value": what, "evidence": [_evidence(document)]},
        "target_status": {"value": "Gold", "evidence": [_evidence(document)]},
        "deadline": {"value": "2026-12-31", "evidence": [_evidence(document)]},
        "action_link": {
            "value": "https://example.com/apply",
            "evidence": [_evidence(document)],
        },
    }


def _brief_response(fact_record, source_url):
    return {
        "schema_version": "1",
        "fact_set_id": str(fact_record.id),
        "title": "Example Air 开放金卡匹配",
        "title_fact_keys": ["what_happened", "target_status"],
        "summary": "符合条件的会员可申请匹配至金卡。",
        "summary_fact_keys": ["what_happened", "target_status"],
        "key_points": [],
        "caveats": [],
        "source_links": [source_url],
    }


def test_same_full_document_is_scoped_to_each_linked_event(db_session) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["Flying Blue costs EUR 199. SAS for India residents costs EUR 99."],
    )
    event.program = "Flying Blue"
    event.target_status = "Gold"
    event.summary = "Flying Blue paid status match"
    first_evidence = db_session.scalar(
        select(EventEvidence).where(EventEvidence.event_id == event.id)
    )
    assert first_evidence is not None
    first_evidence.locator = "Flying Blue paid status match"

    sas_event = StatusEvent(
        created_from_key=f"event-{uuid4()}",
        program="SAS EuroBonus",
        target_status="Gold",
        summary="SAS paid match for India residents",
        search_text="SAS EuroBonus paid match India Gold",
    )
    db_session.add(sas_event)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=sas_event.id,
            document_version_id=documents[0].id,
            hint_index=1,
            source_url=documents[0].canonical_url,
            locator="SAS paid match for India residents",
        )
    )
    db_session.flush()

    flying_blue = _fact_response(
        event, documents[0], what="Flying Blue offers a paid match"
    )
    flying_blue["cost"] = {
        "value": "EUR 199",
        "evidence": [_evidence(documents[0], "Flying Blue sentence")],
    }
    sas = _fact_response(
        sas_event, documents[0], what="SAS offers India residents a paid match"
    )
    sas["cost"] = {
        "value": "EUR 99",
        "evidence": [_evidence(documents[0], "SAS sentence")],
    }
    provider = SequenceAIProvider([flying_blue, sas])

    flying_blue_result = FactConsolidator(db_session, provider).consolidate(event)
    sas_result = FactConsolidator(db_session, provider).consolidate(sas_event)

    first_request = json.loads(provider.calls[0]["user_prompt"])
    second_request = json.loads(provider.calls[1]["user_prompt"])
    assert first_request["event"]["program"] == "Flying Blue"
    assert second_request["event"]["program"] == "SAS EuroBonus"
    assert first_request["materials"][0]["body"] == second_request["materials"][0][
        "body"
    ]
    assert first_request["materials"][0]["linked_event_hint"]["summary"] == (
        "Flying Blue paid status match"
    )
    assert second_request["materials"][0]["linked_event_hint"]["summary"] == (
        "SAS paid match for India residents"
    )
    assert flying_blue_result.fact_set.cost.value == "EUR 199"
    assert sas_result.fact_set.cost.value == "EUR 99"


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


def test_application_window_requires_evidence_and_normalizes_to_beijing(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["Applications run from January 1 through February 28, 2099."],
    )
    response = _fact_response(event, documents[0])
    response["application_start"] = {
        "value": "2099-01-01",
        "evidence": [_evidence(documents[0], "application start sentence")],
    }
    response["deadline"] = {
        "value": "2099-02-28",
        "evidence": [_evidence(documents[0], "application deadline sentence")],
    }

    result = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert result.fact_set.application_start.value == "2099-01-01"
    assert event.application_start_at is not None
    assert event.application_start_at.isoformat().endswith("+08:00")
    assert event.application_start_at.hour == 0
    assert event.application_deadline_at is not None
    assert event.application_deadline_at.isoformat().endswith("+08:00")
    assert event.application_deadline_at.hour == 23
    assert event.application_deadline_at.microsecond == 999999
    assert event.lifecycle_status == "UPCOMING"


def test_weaker_new_source_reuses_current_facts_and_brief(db_session) -> None:
    event, documents = _event_with_documents(
        db_session, ["Match to Gold by December 31 with an application link."]
    )
    first_facts = FactConsolidator(
        db_session,
        SequenceAIProvider([_fact_response(event, documents[0])]),
    ).consolidate(event)
    brief_provider = SequenceAIProvider(
        [_brief_response(first_facts.record, documents[0].canonical_url)]
    )
    first_brief = BriefGenerator(db_session, brief_provider).generate(
        first_facts.record
    )

    weaker_document = _add_document_evidence(
        db_session,
        event,
        "A short article only says the match exists.",
        locator="short match mention",
    )
    weaker_response = {
        "schema_version": "1",
        "event_id": str(event.id),
        "what_happened": {
            "value": "Example Air offers a match to Gold",
            "evidence": [_evidence(weaker_document, "short mention")],
        },
    }
    weaker_provider = SequenceAIProvider([weaker_response])
    second_facts = FactConsolidator(db_session, weaker_provider).consolidate(event)
    second_brief = BriefGenerator(db_session, brief_provider).generate(
        second_facts.record
    )

    request = json.loads(weaker_provider.calls[0]["user_prompt"])
    assert request["current_fact_set"]["deadline"]["value"] == "2026-12-31"
    assert second_facts.reused
    assert second_facts.record.id == first_facts.record.id
    assert second_facts.fact_set.deadline.value == "2026-12-31"
    assert second_brief.reused
    assert second_brief.record.id == first_brief.record.id
    assert len(brief_provider.calls) == 1
    assert db_session.scalar(select(func.count()).select_from(FactSetRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(BriefRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(EventEvidence)) == 2


def test_new_supported_fact_creates_new_fact_set_and_brief(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Match to Gold."])
    first_facts = FactConsolidator(
        db_session,
        SequenceAIProvider([_fact_response(event, documents[0])]),
    ).consolidate(event)
    BriefGenerator(
        db_session,
        SequenceAIProvider(
            [_brief_response(first_facts.record, documents[0].canonical_url)]
        ),
    ).generate(first_facts.record)

    added_document = _add_document_evidence(
        db_session,
        event,
        "The offer is limited to India residents.",
        locator="India eligibility paragraph",
    )
    supplemented = {
        "schema_version": "1",
        "event_id": str(event.id),
        "what_happened": {
            "value": "Example Air offers a match to Gold",
            "evidence": [_evidence(documents[0])],
        },
        "region": {
            "value": "India residents",
            "evidence": [_evidence(added_document, "eligibility paragraph")],
        },
    }
    second_facts = FactConsolidator(
        db_session, SequenceAIProvider([supplemented])
    ).consolidate(event)
    second_brief = BriefGenerator(
        db_session,
        SequenceAIProvider(
            [_brief_response(second_facts.record, added_document.canonical_url)]
        ),
    ).generate(second_facts.record)

    assert not second_facts.reused
    assert second_facts.record.id != first_facts.record.id
    assert second_facts.record.version == 2
    assert second_facts.fact_set.region.value == "India residents"
    assert event.current_fact_set_id == second_facts.record.id
    assert event.current_brief_id == second_brief.record.id
    assert db_session.scalar(select(func.count()).select_from(FactSetRecord)) == 2
    assert db_session.scalar(select(func.count()).select_from(BriefRecord)) == 2


def test_different_known_value_becomes_conflict_instead_of_overwrite(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["The fee is USD 99."])
    first_response = _fact_response(event, documents[0])
    first_response["cost"] = {
        "value": "USD 99",
        "evidence": [_evidence(documents[0], "fee paragraph")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)

    changed_document = _add_document_evidence(
        db_session,
        event,
        "The fee is USD 149.",
        locator="changed fee paragraph",
    )
    changed_response = _fact_response(event, changed_document)
    changed_response["cost"] = {
        "value": "USD 149",
        "evidence": [_evidence(changed_document, "changed fee paragraph")],
    }
    changed = FactConsolidator(
        db_session, SequenceAIProvider([changed_response])
    ).consolidate(event)

    assert changed.record.id != first.record.id
    assert changed.fact_set.cost.value is None
    assert changed.fact_set.cost.conflict
    assert changed.fact_set.cost.alternatives == ["USD 99", "USD 149"]
    assert {
        evidence.document_version_id for evidence in changed.fact_set.cost.evidence
    } == {documents[0].id, changed_document.id}
    assert changed.record.has_conflicts
    assert event.status == "NEEDS_REVIEW"


def test_different_deadline_without_extension_signal_remains_conflicted(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["Apply by September 30, 2026."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["deadline"] = {
        "value": "2026-09-30",
        "evidence": [_evidence(documents[0], "original deadline")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    changed_document = _add_document_evidence(
        db_session,
        event,
        "A second source says October 31 without describing an extension.",
        locator="different deadline",
        relationship="SAME_EVENT",
    )
    changed_response = _fact_response(event, changed_document)
    changed_response["deadline"] = {
        "value": "2026-10-31",
        "evidence": [_evidence(changed_document, "different deadline")],
    }

    changed = FactConsolidator(
        db_session, SequenceAIProvider([changed_response])
    ).consolidate(event)

    assert changed.record.id != first.record.id
    assert changed.fact_set.deadline.conflict
    assert changed.fact_set.deadline.value is None
    assert changed.fact_set.deadline.alternatives == [
        "2026-09-30",
        "2026-10-31",
    ]
    assert event.status == "NEEDS_REVIEW"
    assert event.lifecycle_status == "UNKNOWN"


def test_structured_explicit_extension_advances_deadline_and_restores_archive(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["The original deadline was January 31, 2020."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["deadline"] = {
        "value": "2020-01-31",
        "evidence": [_evidence(documents[0], "original deadline")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    assert event.lifecycle_status == "EXPIRED"
    assert event.archived_at is not None

    extension_document = _add_document_evidence(
        db_session,
        event,
        "The same application deadline is explicitly extended to December 31, 2099.",
        locator="explicit extension sentence",
        relationship="UPDATE_OF",
        deadline_extension=True,
    )
    extension_response = _fact_response(event, extension_document)
    extension_response["deadline"] = {
        "value": "2099-12-31",
        "evidence": [_evidence(extension_document, "explicit extension sentence")],
    }

    extended = FactConsolidator(
        db_session, SequenceAIProvider([extension_response])
    ).consolidate(event)

    assert extended.record.version == 2
    assert extended.fact_set.deadline.value == "2099-12-31"
    assert not extended.fact_set.deadline.conflict
    old_record = db_session.get(FactSetRecord, first.record.id)
    assert old_record is not None
    assert old_record.facts["deadline"]["value"] == "2020-01-31"
    assert event.lifecycle_status == "ACTIVE"
    assert event.archived_at is None


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
