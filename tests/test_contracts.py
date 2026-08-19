from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from journeyplus.contracts import (
    EventHint,
    EvidenceRef,
    FactField,
    OpportunityType,
    RelevanceLabel,
    RelevanceResult,
)


def test_yes_relevance_requires_event_hint() -> None:
    with pytest.raises(ValidationError):
        RelevanceResult(label=RelevanceLabel.YES, confidence=0.9, reason="direct match")


def test_no_relevance_rejects_event_hints() -> None:
    hint = EventHint(
        program="Example",
        opportunity_type=OpportunityType.STATUS_MATCH,
        summary="Example status match",
    )
    with pytest.raises(ValidationError):
        RelevanceResult(
            label=RelevanceLabel.NO,
            confidence=0.9,
            reason="not relevant",
            event_hints=[hint],
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

