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
    with pytest.raises(ValueError, match="Fact consolidation failed after 2 attempts"):
        FactConsolidator(
            db_session, bad_provider, prompt_version="fact-invalid-test"
        ).consolidate(event)
    assert len(bad_provider.calls) == 2
    retry_request = json.loads(bad_provider.calls[1]["user_prompt"])
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "Fact cites a document outside the event"
    )
    failed = db_session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.stage == "FACT_CONSOLIDATION",
            AnalysisRun.prompt_version == "fact-invalid-test",
        )
    )
    assert failed is not None and failed.error is not None
    diagnostics = json.loads(failed.error)
    assert diagnostics["attempt_limit"] == 2
    assert diagnostics["material_count"] == 1
    assert diagnostics["allowed_source_link_count"] == 1
    assert [item["phase"] for item in diagnostics["attempts"]] == [
        "EVIDENCE_REGION_OR_RECONCILIATION_VALIDATION",
        "EVIDENCE_REGION_OR_RECONCILIATION_VALIDATION",
    ]
    assert "Original long body" not in failed.error


def test_fact_retry_uses_validation_correction_and_can_recover(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Match to Gold."])
    invalid = _fact_response(event, documents[0])
    invalid["what_happened"]["evidence"][0]["source_url"] = (
        "https://example.com/not-the-material-source"
    )
    valid = _fact_response(event, documents[0])
    provider = SequenceAIProvider([invalid, valid])

    result = FactConsolidator(
        db_session,
        provider,
        prompt_version="fact-corrected-retry-test",
    ).consolidate(event)

    assert result.fact_set.what_happened.value is not None
    assert len(provider.calls) == 2
    first_request = json.loads(provider.calls[0]["user_prompt"])
    retry_request = json.loads(provider.calls[1]["user_prompt"])
    assert "correction" not in first_request
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "Fact cites a source URL outside the event"
    )


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


def test_equivalent_status_validity_wording_does_not_create_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["Status is valid for 12 months."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["status_validity"] = {
        "value": "12 months",
        "evidence": [_evidence(documents[0], "validity")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    second_document = _add_document_evidence(
        db_session,
        event,
        "Status is valid for twelve months.",
        locator="equivalent validity",
        relationship="SAME_EVENT",
    )
    second_response = _fact_response(event, second_document)
    second_response["status_validity"] = {
        "value": "twelve months",
        "evidence": [_evidence(second_document, "equivalent validity")],
    }

    second = FactConsolidator(
        db_session, SequenceAIProvider([second_response])
    ).consolidate(event)

    assert second.fact_set.status_validity.value == "12 months"
    assert not second.fact_set.status_validity.conflict
    assert second.fact_set.status_validity.alternatives == []
    assert second.record.id == first.record.id


def test_equivalent_status_validity_alternatives_can_resolve_old_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["Status is valid for twelve months."]
    )
    conflicted_response = _fact_response(event, documents[0])
    conflicted_response["status_validity"] = {
        "value": None,
        "evidence": [_evidence(documents[0], "validity")],
        "conflict": True,
        "alternatives": ["12 months", "twelve months"],
    }
    FactConsolidator(
        db_session, SequenceAIProvider([conflicted_response])
    ).consolidate(event)
    second_document = _add_document_evidence(
        db_session,
        event,
        "Status is valid for one year.",
        locator="equivalent validity",
        relationship="SAME_EVENT",
    )
    resolved_response = _fact_response(event, second_document)
    resolved_response["status_validity"] = {
        "value": "one year",
        "evidence": [_evidence(second_document, "equivalent validity")],
    }

    resolved = FactConsolidator(
        db_session, SequenceAIProvider([resolved_response])
    ).consolidate(event)

    assert resolved.fact_set.status_validity.value == "one year"
    assert not resolved.fact_set.status_validity.conflict
    assert resolved.fact_set.status_validity.alternatives == []
    assert event.status == "DRAFT"


def test_same_document_evidence_rewrite_keeps_current_fact_without_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["Elite members of 50+ airline and 20+ hotel programs in Europe may match."],
    )
    first_response = _fact_response(
        event,
        documents[0],
        what="Elite Status Match opportunity to receive Silver or Gold status",
    )
    first_response["eligibility"] = {
        "value": "Elite members of 50+ airline and 20+ hotel programs",
        "evidence": [_evidence(documents[0], "eligibility sentence")],
    }
    first_response["region"] = {
        "value": "Europe, Middle East and Asia",
        "evidence": [_evidence(documents[0], "region sentence")],
    }
    first = FactConsolidator(
        db_session,
        SequenceAIProvider([first_response]),
        prompt_version="same-evidence-v1",
    ).consolidate(event)
    rewritten = _fact_response(
        event,
        documents[0],
        what=(
            "Elite Status Match - paid opportunity for eligible members to receive "
            "Silver or Gold status"
        ),
    )
    rewritten["eligibility"] = {
        "value": "elite members of 50+ airline & 20+ hotel programs",
        "evidence": [_evidence(documents[0], "eligibility sentence")],
    }
    rewritten["region"] = {
        "value": "Europe, the Middle East and Asia",
        "evidence": [_evidence(documents[0], "region sentence")],
    }

    second = FactConsolidator(
        db_session,
        SequenceAIProvider([rewritten]),
        prompt_version="same-evidence-v2",
    ).consolidate(event)

    assert second.reused
    assert second.record.id == first.record.id
    assert second.fact_set.what_happened.value == first.fact_set.what_happened.value
    assert second.fact_set.eligibility.value == first.fact_set.eligibility.value
    assert second.fact_set.region.value == first.fact_set.region.value
    assert not second.record.has_conflicts
    assert event.status == "DRAFT"


def test_multiple_application_routes_do_not_create_cross_route_conflicts(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["UK BA Club elites may use the UK route for GBP 69."],
    )
    first_response = _fact_response(
        event,
        documents[0],
        what="Flying Blue offers a paid status match for UK BA Club elites",
    )
    first_response["eligibility"] = {
        "value": "UK BA Club elite members",
        "evidence": [_evidence(documents[0], "UK eligibility")],
    }
    first_response["region"] = {
        "value": "United Kingdom",
        "evidence": [_evidence(documents[0], "UK region")],
    }
    first_response["cost"] = {
        "value": "GBP 69",
        "evidence": [_evidence(documents[0], "UK price")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    second_document = _add_document_evidence(
        db_session,
        event,
        "Eligible non-alliance elites may use the general route for EUR 99.",
        locator="general route",
        relationship="SAME_EVENT",
    )
    combined = {
        "schema_version": "3",
        "event_id": str(event.id),
        "what_happened": {
            "value": "Flying Blue offers a paid status match through multiple routes",
            "evidence": [
                _evidence(documents[0], "UK route"),
                _evidence(second_document, "general route"),
            ],
        },
        "target_status": {
            "value": "Gold",
            "evidence": [_evidence(documents[0], "target tier")],
        },
        "application_routes": [
            {
                "scope": "UK BA Club route",
                "eligibility": "UK BA Club elite members",
                "region": "United Kingdom",
                "cost": "GBP 69",
                "action_link": "https://example.com/apply/uk",
                "evidence": [_evidence(documents[0], "UK route")],
            },
            {
                "scope": "General non-alliance route",
                "eligibility": "Eligible non-alliance elite members",
                "cost": "EUR 99",
                "action_link": "https://example.com/apply/general",
                "evidence": [_evidence(second_document, "general route")],
            },
        ],
    }
    routed = FactConsolidator(
        db_session, SequenceAIProvider([combined])
    ).consolidate(event)

    assert routed.record.id != first.record.id
    assert routed.fact_set.eligibility.value is None
    assert routed.fact_set.region.value is None
    assert routed.fact_set.cost.value is None
    assert routed.fact_set.action_link.value is None
    assert len(routed.fact_set.application_routes) == 2
    assert not routed.record.has_conflicts
    assert event.status == "DRAFT"

    brief_response = _brief_response(
        routed.record, documents[0].canonical_url
    )
    brief_response["summary"] = "同一活动提供英国和通用两条申请路径。"
    brief_response["summary_fact_keys"] = ["application_routes"]
    brief_response["key_points"] = [
        {
            "text": "英国和通用路径分别适用不同资格与价格。",
            "fact_keys": ["application_routes"],
        }
    ]
    brief_response["source_links"] = [
        documents[0].canonical_url,
        second_document.canonical_url,
    ]
    generated = BriefGenerator(
        db_session, SequenceAIProvider([brief_response])
    ).generate(routed.record)
    assert generated.brief.summary_fact_keys == ["application_routes"]


def test_missing_region_cannot_be_inferred_as_global(db_session) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["Eligible members may apply for the status match."],
    )
    unsupported = _fact_response(event, documents[0])
    unsupported["region"] = {
        "value": "Global",
        "evidence": [_evidence(documents[0], "region is not mentioned")],
    }

    with pytest.raises(ValueError, match="Fact consolidation failed after 2 attempts"):
        FactConsolidator(
            db_session,
            SequenceAIProvider([unsupported, unsupported]),
            prompt_version="unsupported-global-region",
        ).consolidate(event)


def test_structured_explicit_extension_advances_active_deadline(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["The original deadline is January 31, 2098."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["deadline"] = {
        "value": "2098-01-31",
        "evidence": [_evidence(documents[0], "original deadline")],
    }
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    assert event.lifecycle_status == "ACTIVE"
    assert event.archived_at is None

    extension_document = _add_document_evidence(
        db_session,
        event,
        "The same application deadline is explicitly extended to December 31, 2098.",
        locator="explicit extension sentence",
        relationship="UPDATE_OF",
        deadline_extension=True,
    )
    extension_response = _fact_response(event, extension_document)
    extension_response["deadline"] = {
        "value": "2098-12-31",
        "evidence": [_evidence(extension_document, "explicit extension sentence")],
    }

    extended = FactConsolidator(
        db_session, SequenceAIProvider([extension_response])
    ).consolidate(event)

    assert extended.record.version == 2
    assert extended.fact_set.deadline.value == "2098-12-31"
    assert not extended.fact_set.deadline.conflict
    old_record = db_session.get(FactSetRecord, first.record.id)
    assert old_record is not None
    assert old_record.facts["deadline"]["value"] == "2098-01-31"
    assert event.lifecycle_status == "ACTIVE"
    assert event.archived_at is None


def test_automatic_fact_refresh_cannot_restore_archived_event(db_session) -> None:
    event, documents = _event_with_documents(
        db_session, ["The original deadline was January 31, 2020."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["deadline"] = {
        "value": "2020-01-31",
        "evidence": [_evidence(documents[0], "original deadline")],
    }
    FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    archived_at = event.archived_at
    extension_document = _add_document_evidence(
        db_session,
        event,
        "The application deadline is explicitly extended to December 31, 2099.",
        locator="late extension sentence",
        relationship="UPDATE_OF",
        deadline_extension=True,
    )
    extension_response = _fact_response(event, extension_document)
    extension_response["deadline"] = {
        "value": "2099-12-31",
        "evidence": [_evidence(extension_document, "late extension sentence")],
    }

    extended = FactConsolidator(
        db_session, SequenceAIProvider([extension_response])
    ).consolidate(event)

    assert extended.fact_set.deadline.value == "2099-12-31"
    assert event.application_deadline_at is not None
    assert event.application_deadline_at.year == 2099
    assert event.lifecycle_status == "EXPIRED"
    assert event.archived_at == archived_at


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


def test_generic_brand_requirements_become_caveat_and_brief_retry_is_corrected(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Terms, conditions and application requirements differ by airline and "
            "hotel partner. Visit each offer page for details."
        ],
    )
    fact_response = _fact_response(
        event,
        documents[0],
        what="Example Air status match is listed in the digest",
    )
    fact_response["eligibility"] = {
        "value": (
            "Application requirements differ by airline and hotel partner; "
            "visit each offer page"
        ),
        "evidence": [_evidence(documents[0], "digest footer")],
    }
    fact_provider = SequenceAIProvider([fact_response])

    facts = FactConsolidator(db_session, fact_provider).consolidate(event)

    assert facts.fact_set.eligibility.value is None
    assert facts.fact_set.caveats.value == fact_response["eligibility"]["value"]
    assert "这只是 caveats，不是具体 eligibility" in fact_provider.calls[0][
        "system_prompt"
    ]

    invalid_brief = _brief_response(facts.record, documents[0].canonical_url)
    invalid_brief["summary"] = "符合条件的会员需要查看品牌页面的申请要求。"
    invalid_brief["summary_fact_keys"] = ["what_happened", "eligibility"]
    corrected_brief = _brief_response(facts.record, documents[0].canonical_url)
    corrected_brief["summary"] = "邮件提示该匹配存在，具体要求需查看对应活动页。"
    corrected_brief["summary_fact_keys"] = ["what_happened", "caveats"]
    corrected_brief["caveats"] = [
        {
            "text": "各品牌的申请要求可能不同，应以对应活动页为准。",
            "fact_keys": ["caveats"],
        }
    ]
    brief_provider = SequenceAIProvider([invalid_brief, corrected_brief])

    generated = BriefGenerator(db_session, brief_provider).generate(facts.record)

    assert generated.brief.summary_fact_keys == ["what_happened", "caveats"]
    assert generated.brief.caveats[0].fact_keys == ["caveats"]
    assert len(brief_provider.calls) == 2
    first_request = json.loads(brief_provider.calls[0]["user_prompt"])
    second_request = json.loads(brief_provider.calls[1]["user_prompt"])
    assert "caveats" in first_request["known_fact_keys"]
    assert "eligibility" in first_request["unknown_fact_keys"]
    assert "correction" not in first_request
    assert second_request["correction"]["previous_attempt_rejected_for"] == (
        "Brief makes a claim from unknown fact: eligibility"
    )


def test_program_name_is_not_reused_as_target_status(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Example Air link."])
    response = _fact_response(event, documents[0])
    response["target_status"] = {
        "value": "Example Air",
        "evidence": [_evidence(documents[0], "Example Air link")],
    }

    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([response]),
    ).consolidate(event)

    assert facts.fact_set.target_status.value is None


def test_brief_retry_uses_evidence_source_allowlist_not_action_link(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["Match to Gold."])
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([_fact_response(event, documents[0])]),
    ).consolidate(event)
    invalid = _brief_response(facts.record, "https://example.com/apply")
    corrected = _brief_response(facts.record, documents[0].canonical_url)
    provider = SequenceAIProvider([invalid, corrected])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert str(generated.brief.source_links[0]).rstrip("/") == (
        documents[0].canonical_url.rstrip("/")
    )
    assert len(provider.calls) == 2
    first_request = json.loads(provider.calls[0]["user_prompt"])
    second_request = json.loads(provider.calls[1]["user_prompt"])
    assert first_request["allowed_source_links"] == [documents[0].canonical_url]
    assert second_request["correction"]["previous_attempt_rejected_for"] == (
        "Brief contains an unsupported source link"
    )
    assert "action_link" in second_request["correction"]["required_action"]


def test_brief_retry_removes_unknown_absence_descriptions(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Status match digest."])
    response = _fact_response(event, documents[0])
    response["caveats"] = {
        "value": "Requirements differ by brand; visit each offer page.",
        "evidence": [_evidence(documents[0], "digest footer")],
    }
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([response]),
    ).consolidate(event)
    invalid = _brief_response(facts.record, documents[0].canonical_url)
    invalid["summary"] = "资格、地区和截止日期未明确，具体要求需查看品牌页面。"
    invalid["summary_fact_keys"] = ["what_happened", "caveats"]
    corrected = _brief_response(facts.record, documents[0].canonical_url)
    corrected["summary"] = "该会籍匹配的具体要求需以品牌活动页面为准。"
    corrected["summary_fact_keys"] = ["what_happened", "caveats"]
    provider = SequenceAIProvider([invalid, corrected])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert "未明确" not in generated.brief.summary
    retry_request = json.loads(provider.calls[1]["user_prompt"])
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "Brief describes an unknown fact field: eligibility"
    )


def test_brief_retry_requires_caveat_key_for_generic_requirements(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["Status match digest."])
    response = _fact_response(event, documents[0])
    response["caveats"] = {
        "value": "Requirements differ by brand; visit each offer page.",
        "evidence": [_evidence(documents[0], "digest footer")],
    }
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([response]),
    ).consolidate(event)
    invalid = _brief_response(facts.record, documents[0].canonical_url)
    invalid["summary"] = "具体申请要求需查看各品牌页面。"
    invalid["summary_fact_keys"] = ["what_happened", "action_link"]
    corrected = _brief_response(facts.record, documents[0].canonical_url)
    corrected["summary"] = invalid["summary"]
    corrected["summary_fact_keys"] = ["what_happened", "caveats"]
    provider = SequenceAIProvider([invalid, corrected])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert "caveats" in generated.brief.summary_fact_keys
    retry_request = json.loads(provider.calls[1]["user_prompt"])
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "Brief describes generic requirements without citing caveats"
    )


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
    with pytest.raises(ValueError) as exc_info:
        BriefGenerator(db_session, provider).generate(facts.record)
    error_text = str(exc_info.value)
    assert "Brief generation failed after 2 attempts" in error_text
    assert '"attempt":1' in error_text
    assert '"attempt":2' in error_text
    assert error_text.count('"phase":"GROUNDING_VALIDATION"') == 2
    assert "Brief makes a claim from unknown fact: cost" in error_text
    assert long_fact[:180] not in error_text
    failed = db_session.scalar(
        select(AnalysisRun).where(AnalysisRun.stage == "BRIEF_GENERATION")
    )
    assert failed is not None and failed.status == "FAILED"
    diagnostics = json.loads(failed.error)
    assert diagnostics["attempt_limit"] == 2
    assert diagnostics["known_fact_keys"]
    assert diagnostics["allowed_source_link_count"] == 1
    assert [item["attempt"] for item in diagnostics["attempts"]] == [1, 2]


def test_brief_diagnostics_distinguish_model_and_grounding_failures(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["Body"])
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([_fact_response(event, documents[0])]),
    ).consolidate(event)
    bad = _brief_response(facts.record, documents[0].canonical_url)
    bad["key_points"] = [
        {"text": "费用已知。", "fact_keys": ["cost"]},
    ]
    provider = SequenceAIProvider([RuntimeError("temporary timeout"), bad])

    with pytest.raises(ValueError) as exc_info:
        BriefGenerator(db_session, provider).generate(facts.record)

    assert "temporary timeout" in str(exc_info.value)
    failed = db_session.scalar(
        select(AnalysisRun).where(AnalysisRun.stage == "BRIEF_GENERATION")
    )
    assert failed is not None and failed.error is not None
    diagnostics = json.loads(failed.error)
    assert diagnostics["attempts"] == [
        {
            "attempt": 1,
            "phase": "MODEL_GENERATION_OR_SCHEMA_VALIDATION",
            "error_type": "RuntimeError",
            "message": "temporary timeout",
        },
        {
            "attempt": 2,
            "phase": "GROUNDING_VALIDATION",
            "error_type": "ValueError",
            "message": "Brief makes a claim from unknown fact: cost",
        },
    ]
