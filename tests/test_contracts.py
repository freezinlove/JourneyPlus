from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from journeyplus.contracts import (
    DocumentLabel,
    EventHint,
    EvidenceRef,
    FactField,
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
