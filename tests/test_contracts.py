from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from journeyplus.contracts import (
    DocumentLabel,
    EventHint,
    EvidenceRef,
    FactField,
    FactSet,
    RelationshipResult,
    RelevanceResult,
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

    assert facts.schema_version == "2"
    assert facts.application_start.value is None
