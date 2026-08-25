from __future__ import annotations

from uuid import uuid4

import pytest

from journeyplus.contracts import EvidenceRef, StatusMapping
from journeyplus.membership.reconciliation import compare_with_official_mappings
from journeyplus.statusmatch.article_contracts import StatusMatchArticleExtraction
from journeyplus.statusmatch.article_workflow import _validate_extraction


def _mapping(*, target: str = "Gold", conditions: str | None = None):
    return StatusMapping(
        source_program="Example Hotel",
        source_tiers=["Platinum"],
        target_tier=target,
        availability="CONDITIONAL" if conditions else "AVAILABLE",
        conditions=conditions,
        evidence=[
            EvidenceRef(
                document_version_id=uuid4(),
                source_url="https://example.test/article",
                locator="direct mapping",
            )
        ],
    )


def test_mapping_reconciliation_distinguishes_official_candidate_and_conflict() -> None:
    official = _mapping()

    assert compare_with_official_mappings(_mapping(), [official])[0] == "CORROBORATED"
    assert compare_with_official_mappings(_mapping(target="Diamond"), [official])[0] == "CONFLICTING"
    unrelated = _mapping().model_copy(update={"source_program": "Other Hotel"})
    assert compare_with_official_mappings(unrelated, [official])[0] == "CANDIDATE"


def test_candidate_mapping_cannot_invent_a_multi_hop_target() -> None:
    body = "Program A Gold maps directly to Program B Platinum."
    extraction = StatusMatchArticleExtraction.model_validate(
        {
            "candidate_status_mappings": [
                {
                    "source_program": "Program A",
                    "source_tiers": ["Gold"],
                    "target_tier": "Program C Diamond",
                    "availability": "AVAILABLE",
                    "article_quote": body,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="does not directly name"):
        _validate_extraction(extraction, body)
