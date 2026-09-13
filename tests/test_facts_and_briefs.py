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


def _set_document_url(db_session, event, document, url: str) -> None:
    document.canonical_url = url
    item = db_session.get(SourceItem, document.source_item_id)
    assert item is not None
    item.discovered_url = url
    item.canonical_url = url
    evidence = db_session.scalar(
        select(EventEvidence).where(
            EventEvidence.event_id == event.id,
            EventEvidence.document_version_id == document.id,
        )
    )
    assert evidence is not None
    evidence.source_url = url
    db_session.flush()


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


def test_fact_consolidation_preserves_unknowns_and_validates_event_identity(
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
    invalid["event_id"] = str(uuid4())
    bad_provider = SequenceAIProvider([invalid, invalid])
    with pytest.raises(ValueError, match="Fact consolidation failed after 2 attempts"):
        FactConsolidator(
            db_session, bad_provider, prompt_version="fact-invalid-test"
        ).consolidate(event)
    assert len(bad_provider.calls) == 2
    retry_request = json.loads(bad_provider.calls[1]["user_prompt"])
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "FactSet event_id does not match the requested event"
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
    invalid["event_id"] = str(uuid4())
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
        "FactSet event_id does not match the requested event"
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


def test_equivalent_status_validity_date_wording_does_not_create_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["Status valid until December 31, 2027."]
    )
    response = _fact_response(event, documents[0])
    response["status_validity"] = {
        "value": None,
        "evidence": [_evidence(documents[0], "validity")],
        "conflict": True,
        "alternatives": [
            "Status valid until December 31, 2027",
            "Valid until 31 December 2027",
        ],
    }

    result = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert result.fact_set.status_validity.value is not None
    assert "2027" in result.fact_set.status_validity.value
    assert not result.fact_set.status_validity.conflict
    assert event.status == "DRAFT"


def test_statusmatch_home_summary_and_faq_detail_are_refinements(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Eligible airline and hotel status holders may apply.",
            "Applicants also need a member number, eligible-country residence and ID.",
        ],
    )
    _set_document_url(
        db_session, event, documents[0], "https://exampleair.statusmatch.com/"
    )
    _set_document_url(
        db_session, event, documents[1], "https://exampleair.statusmatch.com/faq"
    )
    response = _fact_response(event, documents[0])
    response["eligibility"] = {
        "value": None,
        "evidence": [
            _evidence(documents[0], "homepage summary"),
            _evidence(documents[1], "FAQ eligibility"),
        ],
        "conflict": True,
        "alternatives": [
            "符合条件的航空公司及酒店会籍持有者",
            "必须拥有会员号、所列航空或酒店精英会籍、合资格地区居住证明和身份证件",
        ],
    }

    result = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert not result.fact_set.eligibility.conflict
    assert "身份证件" in (result.fact_set.eligibility.value or "")
    assert not result.record.has_conflicts


def test_statusmatch_later_faq_refines_homepage_without_false_conflicts(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Eligible airline and hotel elite members in Europe, Asia and the "
            "Middle East can apply. Application fees apply. Successful Platinum "
            "members receive D$50 and Titanium members receive D$75."
        ],
    )
    homepage = documents[0]
    _set_document_url(
        db_session, event, homepage, "https://exampleair.statusmatch.com/"
    )
    homepage_response = _fact_response(
        event, homepage, what="Elite members can request a status match"
    )
    homepage_response.update(
        {
            "eligibility": {
                "value": "Eligible airline and hotel elite members",
                "evidence": [_evidence(homepage, "homepage eligibility")],
            },
            "cost": {
                "value": "Application fees apply",
                "evidence": [_evidence(homepage, "generic fee notice")],
            },
            "region": {
                "value": "Europe, Asia & Middle East",
                "evidence": [_evidence(homepage, "homepage regions")],
            },
            "caveats": {
                "value": (
                    "Terms, conditions and fees apply. Successful Platinum members "
                    "receive D$50 and Titanium members receive D$75"
                ),
                "evidence": [_evidence(homepage, "homepage benefit summary")],
            },
        }
    )
    first = FactConsolidator(
        db_session, SequenceAIProvider([homepage_response])
    ).consolidate(event)

    faq = _add_document_evidence(
        db_session,
        event,
        (
            "Applicants need an airline or hotel elite status plus identity and "
            "residency evidence. Platinum receives D$50 and Titanium receives D$75; "
            "only one match is permitted and enrollment closes 20 April 2026."
        ),
        locator="FAQ details",
        relationship="SAME_EVENT",
    )
    _set_document_url(
        db_session, event, faq, "https://exampleair.statusmatch.com/faq"
    )
    faq_response = _fact_response(
        event,
        faq,
        what=(
            "Eligible airline and hotel elite members can request a paid match "
            "after supplying identity and residency evidence"
        ),
    )
    faq_response.update(
        {
            "eligibility": {
                "value": (
                    "Applicants need airline or hotel elite status, a member number, "
                    "identity document and eligible-region residency"
                ),
                "evidence": [_evidence(faq, "FAQ eligibility")],
            },
            "cost": {
                "value": "Platinum: USD 49; Titanium: USD 199",
                "evidence": [_evidence(faq, "FAQ fee table")],
            },
            "region": {
                "value": "Europe, Asia, Middle East",
                "evidence": [_evidence(faq, "FAQ regions")],
            },
            "caveats": {
                "value": (
                    "Platinum receives D$50 and Titanium receives D$75; only one "
                    "match is permitted; enrollment closes 20 April 2026"
                ),
                "evidence": [_evidence(faq, "FAQ limitations")],
            },
        }
    )
    second = FactConsolidator(
        db_session, SequenceAIProvider([faq_response])
    ).consolidate(event)

    assert first.fact_set.cost.value is None
    assert second.fact_set.cost.value == "Platinum: USD 49; Titanium: USD 199"
    assert second.fact_set.region.value in {
        "Europe, Asia & Middle East",
        "Europe, Asia, Middle East",
    }
    assert "identity" in (second.fact_set.eligibility.value or "")
    assert "20 April 2026" in (second.fact_set.caveats.value or "")
    assert not second.record.has_conflicts
    assert event.status == "DRAFT"


def test_statusmatch_upgrade_voucher_exclusion_wording_is_not_a_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Eligible members receive all benefits except upgrade vouchers. "
            "Hotel applicants can only receive Silver Jay."
        ],
    )
    _set_document_url(
        db_session, event, documents[0], "https://rj.statusmatch.com/faq"
    )
    response = _fact_response(event, documents[0])
    response["caveats"] = {
        "value": None,
        "evidence": [_evidence(documents[0], "benefit limitations")],
        "conflict": True,
        "alternatives": [
            "符合条件的会员可获得除升级券外的所有礼遇",
            (
                "符合条件的会员在会籍匹配期间不获得升级券，直到重新获得该等级资格；"
                "酒店匹配申请人只能获得 Silver Jay 等级，Gold Sparrow 不可用"
            ),
        ],
    }

    result = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert not result.fact_set.caveats.conflict
    assert "酒店" in (result.fact_set.caveats.value or "")
    assert not result.record.has_conflicts
    assert event.status == "DRAFT"


def test_statusmatch_external_registration_is_not_the_application_entry(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["Apply for Gold."])
    _set_document_url(
        db_session, event, documents[0], "https://clubavolta.statusmatch.com/"
    )
    response = _fact_response(event, documents[0])
    response["action_link"] = {
        "value": "https://sso.clubavolta.com/register?source=statusmatch",
        "evidence": [_evidence(documents[0], "Step 1 registration")],
    }
    response["application_routes"] = [
        {
            "scope": "Club Avolta Gold route",
            "eligibility": "Eligible airline or hotel loyalty members",
            "action_link": "https://sso.clubavolta.com/register?source=statusmatch",
            "evidence": [_evidence(documents[0], "Step 1 registration")],
        }
    ]

    result = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert result.fact_set.action_link.value == "https://clubavolta.statusmatch.com/"
    route_link = result.fact_set.application_routes[0].action_link
    assert route_link is not None
    assert str(route_link) == "https://clubavolta.statusmatch.com/"
    assert type(route_link).__name__ == "HttpUrl"


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

    assert resolved.fact_set.status_validity.value == "twelve months"
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


def test_routes_with_the_same_application_link_reconcile_by_scope(db_session) -> None:
    event, documents = _event_with_documents(
        db_session, ["Airline and travel-card routes share one application page."]
    )
    first_response = _fact_response(event, documents[0])
    first_response["application_routes"] = [
        {
            "scope": "Airline status route",
            "eligibility": "Eligible airline elites",
            "cost": "USD 99",
            "action_link": "https://example.com/apply",
            "evidence": [_evidence(documents[0], "airline route")],
        },
        {
            "scope": "Travel card route",
            "eligibility": "Eligible travel card holders",
            "cost": "Silver USD 99; Gold and Platinum unavailable",
            "action_link": "https://example.com/apply",
            "evidence": [_evidence(documents[0], "travel card route")],
        },
    ]
    first = FactConsolidator(
        db_session, SequenceAIProvider([first_response])
    ).consolidate(event)
    added = _add_document_evidence(
        db_session,
        event,
        "The airline route remains available.",
        locator="airline route refresh",
        relationship="SAME_EVENT",
    )
    refreshed = _fact_response(event, added)
    refreshed["application_routes"] = [
        {
            "scope": "Airline status route",
            "eligibility": "Eligible airline elites",
            "cost": "USD 99",
            "action_link": "https://example.com/apply",
            "evidence": [_evidence(added, "airline route refresh")],
        }
    ]

    second = FactConsolidator(
        db_session, SequenceAIProvider([refreshed])
    ).consolidate(event)

    assert first.fact_set.application_routes[1].scope == "Travel card route"
    assert [route.scope for route in second.fact_set.application_routes] == [
        "Airline status route",
        "Travel card route",
    ]
    assert second.fact_set.application_routes[1].cost == (
        "Silver USD 99; Gold and Platinum unavailable"
    )


def test_statusmatch_tier_table_is_structured_and_available_to_briefs(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Example Air Gold and Platinum map to Target Gold; "
            "Target Platinum is unavailable."
        ],
    )
    response = _fact_response(event, documents[0])
    response["status_mappings"] = [
        {
            "source_program": "Example Air",
            "source_tiers": ["Gold", "Platinum"],
            "target_tier": "Target Gold",
            "availability": "AVAILABLE",
            "evidence": [_evidence(documents[0], "tier mapping table")],
        },
        {
            "source_program": "Example Air",
            "source_tiers": [],
            "target_tier": "Target Platinum",
            "availability": "UNAVAILABLE",
            "evidence": [_evidence(documents[0], "tier mapping table")],
        },
    ]
    fact_provider = SequenceAIProvider([response])

    facts = FactConsolidator(db_session, fact_provider).consolidate(event)

    assert facts.fact_set.schema_version == "5"
    assert len(facts.fact_set.status_mappings) == 2
    assert facts.fact_set.status_mappings[0].source_tiers == ["Gold", "Platinum"]
    assert facts.fact_set.status_mappings[1].availability == "UNAVAILABLE"
    assert "Recently ended offers" in fact_provider.calls[0]["system_prompt"]
    assert "仍会被解析" in fact_provider.calls[0]["system_prompt"]

    brief = _brief_response(facts.record, documents[0].canonical_url)
    brief["summary"] = "Example Air 金卡及白金卡可匹配到目标金卡。"
    brief["summary_fact_keys"] = ["status_mappings"]
    generated = BriefGenerator(
        db_session, SequenceAIProvider([brief])
    ).generate(facts.record)

    assert generated.brief.summary_fact_keys == ["status_mappings"]


def test_statusmatch_html_table_is_injected_without_model_copying_rows(
    db_session,
) -> None:
    html = """
    <table>
      <tr><td></td><td colspan="2">Target Club Tier</td></tr>
      <tr><td>AIRLINE</td><td>SILVER</td><td>GOLD</td></tr>
      <tr><td><strong>Example Air</strong><p>Rewards</p></td>
          <td>Silver<br></td><td>Gold<br>Platinum<br></td></tr>
    </table>
    """
    event, documents = _event_with_documents(db_session, [html])
    document = documents[0]
    document.canonical_url = "https://example.statusmatch.com/faq"
    document.raw_body = html
    document.normalized_body = html
    response = _fact_response(event, document)
    response["status_mappings"] = []
    provider = SequenceAIProvider([response])

    result = FactConsolidator(db_session, provider).consolidate(event)

    assert len(result.fact_set.status_mappings) == 2
    assert result.fact_set.status_mappings[1].source_tiers == ["Gold", "Platinum"]
    request = json.loads(provider.calls[0]["user_prompt"])
    assert request["evidence_rules"]["deterministic_status_mapping_count"] == 2


def test_missing_region_remains_unknown_without_evidence(db_session) -> None:
    event, documents = _event_with_documents(
        db_session, ["Eligible members may apply for the status match."],
    )
    response = _fact_response(event, documents[0])
    response["region"] = {"value": None}
    provider = SequenceAIProvider([response])
    result = FactConsolidator(db_session, provider).consolidate(event)
    assert result.fact_set.region.value is None
    assert "不得把“未提及地域”推断为全球" in provider.calls[0]['system_prompt']


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


def test_generic_brand_requirements_are_not_promoted_to_business_facts(
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
    assert facts.fact_set.caveats.value is None
    assert "Gmail 邮件仅用于发现" in fact_provider.calls[0]["system_prompt"]
    assert "通用兜底文字不得代替具体事实" in fact_provider.calls[0][
        "system_prompt"
    ]


def test_generic_caveat_clause_is_removed_without_losing_specific_limits(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        ["Terms, conditions and fees apply. Platinum companion is excluded."],
    )
    response = _fact_response(event, documents[0])
    response["caveats"] = {
        "value": None,
        "evidence": [_evidence(documents[0], "terms and exclusions")],
        "conflict": True,
        "alternatives": [
            "Terms, conditions and fees apply",
            "条款、条件及费用适用；匹配的铂金会员不享受铂金同伴特权；申请费批准后不可退还。",
        ],
    }

    facts = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert not facts.fact_set.caveats.conflict
    assert facts.fact_set.caveats.value == (
        "匹配的铂金会员不享受铂金同伴特权；申请费批准后不可退还"
    )
    assert not facts.record.has_conflicts


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
    corrected["summary"] = "该会籍匹配活动已经发布。"
    corrected["summary_fact_keys"] = ["what_happened"]
    provider = SequenceAIProvider([invalid, corrected])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert "未明确" not in generated.brief.summary
    retry_request = json.loads(provider.calls[1]["user_prompt"])
    assert retry_request["correction"]["previous_attempt_rejected_for"] == (
        "Brief describes an unknown fact field: eligibility"
    )


def test_brief_retry_removes_generic_page_reference_even_with_caveat_evidence(
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
    invalid["summary_fact_keys"] = ["what_happened", "caveats"]
    corrected = _brief_response(facts.record, documents[0].canonical_url)
    corrected["summary"] = "该会籍匹配活动已经发布。"
    corrected["summary_fact_keys"] = ["what_happened"]
    provider = SequenceAIProvider([invalid, corrected])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert generated.brief.summary_fact_keys == ["what_happened"]
    assert "查看" not in generated.brief.summary
    retry_request = json.loads(provider.calls[1]["user_prompt"])
    rejection = retry_request["correction"]["previous_attempt_rejected_for"]
    assert rejection.startswith(
        "Brief uses a generic page-reference caveat instead of concrete facts | "
    )
    diagnostic = json.loads(rejection.split(" | ", maxsplit=1)[1])
    assert diagnostic == {
        "rule_id": "BRIEF_GENERIC_PAGE_REFERENCE",
        "claim_location": "summary",
        "claim_term": "申请要求",
        "reference_term": "页面",
        "matched_text": "申请要求需查看各品牌页面",
        "claim_excerpt": "具体申请要求需查看各品牌页面。",
        "fact_keys": ["caveats", "what_happened"],
    }
    assert "删除" in retry_request["correction"]["required_action"]


def test_brief_generic_page_reference_allows_concrete_fee_difference(
    db_session,
) -> None:
    event, documents = _event_with_documents(db_session, ["Status match terms."])
    response = _fact_response(event, documents[0])
    response["eligibility"] = {
        "value": "Kenya Airways eligible members",
        "evidence": [_evidence(documents[0], "eligibility section")],
    }
    response["application_routes"] = [
        {
            "scope": "Airline status route",
            "eligibility": "Eligible airline elite members",
            "region": "Americas",
            "cost": "Silver 99 USD; Gold/Platinum 299 USD",
            "action_link": "https://example.com/apply/airline",
            "evidence": [_evidence(documents[0], "airline route")],
        },
        {
            "scope": "Hotel status route",
            "eligibility": "Eligible hotel elite members",
            "action_link": "https://example.com/apply/hotel",
            "evidence": [_evidence(documents[0], "hotel route")],
        },
        {
            "scope": "Travel card route",
            "eligibility": "Eligible travel card holders",
            "action_link": "https://example.com/apply/card",
            "evidence": [_evidence(documents[0], "travel card route")],
        },
    ]
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([response]),
    ).consolidate(event)
    candidate = _brief_response(facts.record, documents[0].canonical_url)
    candidate["key_points"] = [
        {
            "text": "申请条件适用于 Kenya Airways 合资格会员。",
            "fact_keys": ["eligibility"],
        },
        {
            "text": (
                "提供航司身份、酒店身份、旅行信用卡三种匹配路径，"
                "不同路径和地区费用不同。例如，航司身份匹配中，美洲地区"
                "Silver 99 USD、Gold/Platinum 299 USD。"
            ),
            "fact_keys": ["application_routes"],
        },
    ]
    provider = SequenceAIProvider([candidate])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert len(generated.brief.key_points) == 2
    assert len(provider.calls) == 1


def test_conflicts_enter_review_but_still_generate_a_visible_chinese_brief(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session, ["The fee is USD 99 in one place and USD 149 in another."]
    )
    response = _fact_response(event, documents[0])
    response["cost"] = {
        "value": None,
        "evidence": [_evidence(documents[0], "two fee statements")],
        "conflict": True,
        "alternatives": ["USD 99", "USD 149"],
    }
    facts = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)
    candidate = _brief_response(facts.record, documents[0].canonical_url)
    provider = SequenceAIProvider([candidate])

    generated = BriefGenerator(db_session, provider).generate(facts.record)

    assert event.status == "NEEDS_REVIEW"
    assert event.current_brief_id == generated.record.id
    conflict_points = [
        point for point in generated.brief.caveats if "cost" in point.fact_keys
    ]
    assert len(conflict_points) == 1
    assert "USD 99" in conflict_points[0].text
    assert "USD 149" in conflict_points[0].text
    assert "待复核" in conflict_points[0].text


def test_statusmatch_prose_unavailability_overrides_stale_table_amount(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Recently ended offers are listed below in the page navigation.\n\n"
            "Argentina, Brazil, Chile | Platinum: USD 399 | Not Available for Brazil. "
            "Platinum status match is not available for Argentina, Brazil, Chila, "
            "Hong Kong, Taiwan or China residents.\n\n"
            "### Recently ended offers\nOld China offer."
        ],
    )
    _set_document_url(
        db_session, event, documents[0], "https://flyingblue.statusmatch.com/faq"
    )
    response = _fact_response(event, documents[0])
    response["target_status"] = {
        "value": "Silver, Gold, Platinum（阿根廷和智利存在冲突）",
        "evidence": [_evidence(documents[0], "table and prose")],
        "conflict": True,
        "alternatives": ["Silver", "Gold", "Platinum"],
    }
    response["caveats"] = {
        "value": (
            "每人仅限一次匹配；Platinum在阿根廷和智利的表格与正文存在冲突；"
            "申请费可能变更"
        ),
        "evidence": [_evidence(documents[0], "current conditions")],
    }
    response["application_routes"] = [
        {
            "scope": "South America",
            "region": "Argentina, Brazil, Chile, Colombia",
            "cost": "Silver: USD 99; Gold: USD 299; Platinum: USD 399 (Not Available for Brazil)",
            "prices": [
                {
                    "target_tier": "Silver",
                    "amount": 99,
                    "currency": "USD",
                    "availability": "AVAILABLE",
                    "raw_text": "USD 99",
                    "evidence": [_evidence(documents[0], "current regional fee table")],
                },
                {
                    "target_tier": "Gold",
                    "amount": 299,
                    "currency": "USD",
                    "availability": "AVAILABLE",
                    "raw_text": "USD 299",
                    "evidence": [_evidence(documents[0], "current regional fee table")],
                },
                {
                    "target_tier": "Platinum",
                    "amount": 399,
                    "currency": "USD",
                    "availability": "AVAILABLE",
                    "raw_text": "USD 399",
                    "evidence": [_evidence(documents[0], "current regional fee table")],
                },
            ],
            "evidence": [_evidence(documents[0], "current regional fee table")],
        }
    ]
    facts = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert event.status != "NEEDS_REVIEW"
    assert not facts.record.has_conflicts
    assert [route.region for route in facts.fact_set.application_routes] == [
        "Colombia",
        "Argentina, Brazil, Chile",
    ]
    available, unavailable = facts.fact_set.application_routes
    assert available.prices[-1].amount == 399
    assert unavailable.prices[-1].amount is None
    assert unavailable.prices[-1].currency is None
    assert unavailable.prices[-1].availability == "UNAVAILABLE"
    assert "正文明确" in unavailable.prices[-1].raw_text
    assert not facts.fact_set.target_status.conflict
    assert facts.fact_set.target_status.value == "Silver, Gold, Platinum"
    assert "存在冲突" not in (facts.fact_set.caveats.value or "")
    assert "历史费用表残留金额" in (facts.fact_set.caveats.value or "")


def test_impossible_post_expiry_link_date_marks_deadline_conflict(
    db_session,
) -> None:
    event, documents = _event_with_documents(
        db_session,
        [
            "Applications run from May 1, 2026 until September 1, 2026. "
            "This link will be active two weeks after the offer expires, until "
            "20 April 2026, and will be automatically deactivated after that date."
        ],
    )
    _set_document_url(
        db_session, event, documents[0], "https://ghadiscovery.statusmatch.com/faq"
    )
    response = _fact_response(event, documents[0])
    response["application_start"] = {
        "value": "May 1, 2026",
        "evidence": [_evidence(documents[0], "application window")],
    }
    response["deadline"] = {
        "value": "September 1, 2026",
        "evidence": [_evidence(documents[0], "application window")],
    }

    facts = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)

    assert facts.fact_set.deadline.conflict
    assert "September 1, 2026" in facts.fact_set.deadline.alternatives
    assert any("20 April 2026" in item for item in facts.fact_set.deadline.alternatives)
    assert facts.record.has_conflicts
    assert event.status == "NEEDS_REVIEW"
    assert event.lifecycle_status == "UNKNOWN"


def test_brief_replaces_internal_fact_keys_with_chinese_labels(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Three application routes."])
    response = _fact_response(event, documents[0])
    response["application_routes"] = [
        {
            "scope": "Travel card route",
            "eligibility": "Eligible travel card holders",
            "cost": "USD 99",
            "evidence": [_evidence(documents[0], "travel card route")],
        }
    ]
    facts = FactConsolidator(
        db_session, SequenceAIProvider([response])
    ).consolidate(event)
    candidate = _brief_response(facts.record, documents[0].canonical_url)
    candidate["key_points"] = [
        {
            "text": "具体费用详见application_routes。",
            "fact_keys": ["application_routes"],
        }
    ]

    generated = BriefGenerator(
        db_session, SequenceAIProvider([candidate])
    ).generate(facts.record)

    assert "application_routes" not in generated.brief.key_points[0].text
    assert "申请路径" in generated.brief.key_points[0].text


def test_brief_rejects_standalone_generic_terms_apply(db_session) -> None:
    event, documents = _event_with_documents(db_session, ["Status match terms."])
    response = _fact_response(event, documents[0])
    response["caveats"] = {
        "value": "申请费批准后不可退还。",
        "evidence": [_evidence(documents[0], "footer")],
    }
    facts = FactConsolidator(
        db_session,
        SequenceAIProvider([response]),
    ).consolidate(event)
    candidate = _brief_response(facts.record, documents[0].canonical_url)
    candidate["caveats"] = [
        {"text": "条款和费用适用。", "fact_keys": ["caveats"]}
    ]
    provider = SequenceAIProvider([candidate, candidate])

    with pytest.raises(ValueError):
        BriefGenerator(db_session, provider).generate(facts.record)

    failed = db_session.scalar(
        select(AnalysisRun).where(AnalysisRun.stage == "BRIEF_GENERATION")
    )
    assert failed is not None and failed.error is not None
    diagnostics = json.loads(failed.error)
    detail = json.loads(
        diagnostics["attempts"][0]["message"].split(" | ", maxsplit=1)[1]
    )
    assert detail["rule_id"] == "BRIEF_GENERIC_TERMS_APPLY"
    assert detail["claim_location"] == "caveats[0]"
    assert detail["claim_term"] == "条款和费用"
    assert detail["reference_term"] == "适用"


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
