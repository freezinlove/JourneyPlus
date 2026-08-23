from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from journeyplus.contracts import (
    ApplicationRoute,
    DocumentLabel,
    EventHint,
    EvidenceRef,
    FactField,
    FactSet,
    RelationshipResult,
    RelevanceResult,
    StatusMapping,
)


def test_status_opportunity_classification_requires_event_hint() -> None:
    with pytest.raises(ValidationError):
        RelevanceResult(
            label=DocumentLabel.STATUS_OPPORTUNITY,
            confidence=0.9,
            reason="direct match",
        )


def test_none_classification_rejects_event_hints() -> None:
    hint = EventHint(
        program="Example",
        summary="Example status match",
    )
    with pytest.raises(ValidationError):
        RelevanceResult(
            label=DocumentLabel.NONE,
            confidence=0.9,
            reason="not relevant",
            event_hints=[hint],
        )


def test_removed_opportunity_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventHint.model_validate(
            {
                "program": "Example",
                "summary": "Example status match",
                "opportunity_type": "STATUS_MATCH",
            }
        )


def test_event_hint_accepts_a_long_but_bounded_region_summary() -> None:
    hint = EventHint(
        program="Royal Jordanian Royal Club",
        summary="Paid status match",
        region_hint="x" * 500,
    )

    assert len(hint.region_hint or "") == 500


def test_event_hint_preserves_optional_application_window_text() -> None:
    hint = EventHint(
        program="Example Air",
        summary="Status match",
        application_start="2026-09-01",
        application_deadline="2026-09-30 18:00+08:00",
    )

    assert hint.application_start == "2026-09-01"
    assert hint.application_deadline == "2026-09-30 18:00+08:00"


def test_deadline_extension_is_structured_and_requires_update_relationship() -> None:
    valid = RelationshipResult(
        relationship="UPDATE_OF",
        confidence=1,
        reason="deadline explicitly extended",
        deadline_extension=True,
    )
    assert valid.deadline_extension

    with pytest.raises(ValidationError):
        RelationshipResult(
            relationship="SAME_EVENT",
            confidence=1,
            reason="invalid extension flag",
            deadline_extension=True,
        )


def test_legacy_yes_no_labels_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RelevanceResult.model_validate(
            {"label": "YES", "confidence": 0.9, "reason": "legacy result"}
        )

    with pytest.raises(ValidationError):
        RelevanceResult.model_validate(
            {
                "label": ["STATUS_OPPORTUNITY", "NONE"],
                "confidence": 0.9,
                "reason": "stacked labels",
            }
        )


def test_known_fact_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        FactField(value="2026-12-31")

    field = FactField(
        value="2026-12-31",
        evidence=[
            EvidenceRef(
                document_version_id=uuid4(),
                source_url="https://example.com/source",
                locator="paragraph 3",
            )
        ],
    )
    assert field.value == "2026-12-31"


def test_fact_set_has_unknown_application_start_by_default() -> None:
    facts = FactSet(
        event_id=uuid4(),
        what_happened=FactField(),
    )

    assert facts.schema_version == "4"
    assert facts.application_start.value is None
    assert facts.application_routes == []
    assert facts.status_mappings == []


def test_fact_set_treats_explicit_null_optional_fields_as_unknown() -> None:
    facts = FactSet.model_validate(
        {
            "event_id": str(uuid4()),
            "what_happened": {},
            "eligibility": None,
            "target_status": None,
            "cost": None,
            "challenge_requirements": None,
            "region": None,
            "application_start": None,
            "deadline": None,
            "status_validity": None,
            "action_link": None,
            "caveats": None,
            "application_routes": None,
            "status_mappings": None,
        }
    )

    assert facts.eligibility.value is None
    assert facts.target_status.value is None
    assert facts.application_routes == []
    assert facts.status_mappings == []


def test_application_route_requires_evidence_and_scoped_detail() -> None:
    evidence = EvidenceRef(
        document_version_id=uuid4(),
        source_url="https://example.com/route",
        locator="route terms",
    )

    route = ApplicationRoute(
        scope="UK BA Club members",
        eligibility="British Airways Club elite members in the UK",
        action_link="https://example.com/route",
        evidence=[evidence],
    )

    assert route.region is None
    with pytest.raises(ValidationError):
        ApplicationRoute(scope="empty", evidence=[evidence])
    with pytest.raises(ValidationError):
        ApplicationRoute(
            scope="inconsistent conflict",
            eligibility="members",
            evidence=[evidence],
            conflict=True,
        )


def test_status_mapping_requires_tiers_unless_explicitly_unavailable() -> None:
    evidence = EvidenceRef(
        document_version_id=uuid4(),
        source_url="https://example.statusmatch.com/faq",
        locator="airline tier mapping table",
    )
    mapping = StatusMapping(
        source_program="Example Air",
        source_tiers=["Gold", "Platinum"],
        target_tier="Target Gold",
        availability="AVAILABLE",
        evidence=[evidence],
    )
    unavailable = StatusMapping(
        source_program="Example Air",
        source_tiers=[],
        target_tier="Target Platinum",
        availability="UNAVAILABLE",
        evidence=[evidence],
    )

    assert mapping.source_tiers == ["Gold", "Platinum"]
    assert unavailable.source_tiers == []
    with pytest.raises(ValidationError):
        StatusMapping(
            source_program="Example Air",
            source_tiers=[],
            target_tier="Target Gold",
            availability="AVAILABLE",
            evidence=[evidence],
        )
    with pytest.raises(ValidationError):
        StatusMapping(
            source_program="Example Air",
            source_tiers=["Gold"],
            target_tier="Target Platinum",
            availability="UNAVAILABLE",
            evidence=[evidence],
        )
    with pytest.raises(ValidationError):
        StatusMapping(
            source_program="Example Air",
            source_tiers=["Gold"],
            target_tier="Target Gold",
            availability="CONDITIONAL",
            evidence=[evidence],
        )
