from __future__ import annotations

from journeyplus.statusmatch.article_contracts import StatusMatchArticleExtraction
from journeyplus.statusmatch.article_workflow import _validate_extraction


def test_legacy_candidate_mapping_is_accepted_but_excluded_and_ignored() -> None:
    body = "Program A Gold maps directly to Program B Platinum."
    extraction = StatusMatchArticleExtraction.model_validate(
        {
            "schema_version": "2",
            "highlights": [],
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

    _validate_extraction(extraction, body)

    assert len(extraction.candidate_status_mappings) == 1
    assert "candidate_status_mappings" not in extraction.model_dump(mode="json")
    assert (
        "candidate_status_mappings"
        not in StatusMatchArticleExtraction.model_json_schema()["properties"]
    )
