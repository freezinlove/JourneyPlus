from __future__ import annotations

from journeyplus.statusmatch.article_contracts import StatusMatchArticleExtraction
from journeyplus.statusmatch.article_workflow import _validate_extraction


def test_article_extraction_only_contains_highlight_text() -> None:
    extraction = StatusMatchArticleExtraction.model_validate(
        {
            "schema_version": "3",
            "highlights": ["  文章提醒这项权益存在使用限制。  "],
        }
    )

    _validate_extraction(extraction)

    assert extraction.model_dump(mode="json") == {
        "schema_version": "3",
        "highlights": ["文章提醒这项权益存在使用限制。"],
    }
    assert set(StatusMatchArticleExtraction.model_json_schema()["properties"]) == {
        "schema_version",
        "highlights",
    }
