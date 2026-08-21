from __future__ import annotations

import hashlib
import json

import pytest

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.contracts import RelevanceResult
from journeyplus.evaluation.runtime import JsonCachingProvider, run_gold_baseline


def _none(reason: str = "not a direct status opportunity") -> dict:
    return {
        "label": "NONE",
        "confidence": 0.99,
        "reason": reason,
        "event_hints": [],
    }


def _status_with_two_events() -> dict:
    return {
        "label": "STATUS_OPPORTUNITY",
        "confidence": 0.98,
        "reason": "two direct and independent status opportunities",
        "event_hints": [
            {
                "program": "Example Air",
                "opportunity_type": "STATUS_MATCH",
                "summary": "Match to Gold",
                "target_status": "Gold",
            },
            {
                "program": "Example Hotel",
                "opportunity_type": "FAST_TRACK",
                "summary": "Fast track to Platinum",
                "target_status": "Platinum",
            },
        ],
    }


def _write_frozen_dataset(tmp_path, classifications=None):
    classifications = classifications or [
        {
            "document_key": "doc-1",
            "label": "NONE",
            "event_keys": [],
        },
        {
            "document_key": "doc-2",
            "label": "NONE",
            "event_keys": [],
        },
    ]
    documents = [
        {
            "document_key": item["document_key"],
            "source_url": f"https://example.com/{index}",
            "normalized_body": f"Frozen body {index}",
        }
        for index, item in enumerate(classifications, start=1)
    ]
    dataset = {
        "schema_version": "2",
        "dataset_version": 1,
        "cases": [
            {
                "case_id": "case-1",
                "version": 1,
                "documents": documents,
                "classifications": classifications,
                "relationships": [],
                "facts": [],
            }
        ],
    }
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset), encoding="utf-8")
    counts = {
        "documents": len(documents),
        "status_opportunity": sum(
            item["label"] == "STATUS_OPPORTUNITY" for item in classifications
        ),
        "none": sum(item["label"] == "NONE" for item in classifications),
        "uncertain": sum(
            item["label"] == "UNCERTAIN" for item in classifications
        ),
    }
    freeze_path = tmp_path / "gold.freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                "freeze_schema_version": 1,
                "schema_version": "2",
                "dataset_version": 1,
                "sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
                "case_versions": {"case-1": 1},
                "counts": counts,
            }
        ),
        encoding="utf-8",
    )
    return gold_path, freeze_path


def test_freeze_mismatch_stops_before_model_call(tmp_path) -> None:
    gold_path, freeze_path = _write_frozen_dataset(tmp_path)
    gold_path.write_text(gold_path.read_text() + "\n", encoding="utf-8")
    provider = SequenceAIProvider([_none()])

    with pytest.raises(ValueError, match="SHA-256"):
        run_gold_baseline(
            provider=provider,
            gold_path=gold_path,
            freeze_path=freeze_path,
            output_dir=tmp_path / "run",
        )

    assert provider.calls == []
    assert not (tmp_path / "run").exists()


def test_cache_is_scoped_and_prompt_identity_keeps_old_outputs(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    first_delegate = SequenceAIProvider([_none("first")])
    first = JsonCachingProvider(
        first_delegate,
        cache_path,
        run_identity={"status_prompt_version": "v1"},
    )
    first.set_document_scope("case-1", "doc-1")
    result = first.generate_structured(
        system_prompt="classify-v1",
        user_prompt="body",
        output_model=RelevanceResult,
    )
    assert result.reason == "first"

    replay_delegate = SequenceAIProvider([])
    replay = JsonCachingProvider(
        replay_delegate,
        cache_path,
        run_identity={"status_prompt_version": "v1"},
    )
    replay.set_document_scope("case-1", "doc-1")
    replay.generate_structured(
        system_prompt="classify-v1",
        user_prompt="body",
        output_model=RelevanceResult,
    )
    assert replay.cache_hits == 1
    assert replay_delegate.calls == []

    upgraded_delegate = SequenceAIProvider([_none("upgraded")])
    upgraded = JsonCachingProvider(
        upgraded_delegate,
        cache_path,
        run_identity={"status_prompt_version": "v2"},
    )
    upgraded.set_document_scope("case-1", "doc-1")
    upgraded.generate_structured(
        system_prompt="classify-v1",
        user_prompt="body",
        output_model=RelevanceResult,
    )
    assert upgraded.model_calls == 1
    assert len(json.loads(cache_path.read_text())["entries"]) == 2


def test_interrupted_run_uses_cache_and_only_calls_missing_document(tmp_path) -> None:
    gold_path, freeze_path = _write_frozen_dataset(tmp_path)
    output_dir = tmp_path / "run"
    first_provider = SequenceAIProvider([_none("first")])
    first = run_gold_baseline(
        provider=first_provider,
        gold_path=gold_path,
        freeze_path=freeze_path,
        output_dir=output_dir,
        max_documents=1,
    )
    assert not first.complete
    assert first.model_calls == 1

    first.state_database_path.unlink()
    resumed_provider = SequenceAIProvider([_none("second")])
    resumed = run_gold_baseline(
        provider=resumed_provider,
        gold_path=gold_path,
        freeze_path=freeze_path,
        output_dir=output_dir,
    )

    assert resumed.complete
    assert resumed.cache_hits == 1
    assert resumed.model_calls == 1
    assert len(resumed_provider.calls) == 1
    report = json.loads(resumed.report_path.read_text())
    assert report["evaluation"]["document_labels"]["score"] == 1


def test_multi_event_prediction_is_stable_and_id_independent(tmp_path) -> None:
    classifications = [
        {
            "document_key": "doc-1",
            "label": "STATUS_OPPORTUNITY",
            "event_keys": ["gold-event-a", "gold-event-b"],
        }
    ]
    gold_path, freeze_path = _write_frozen_dataset(tmp_path, classifications)
    output_dir = tmp_path / "run"
    first = run_gold_baseline(
        provider=SequenceAIProvider([_status_with_two_events()]),
        gold_path=gold_path,
        freeze_path=freeze_path,
        output_dir=output_dir,
    )
    first_prediction = json.loads(first.prediction_path.read_text())
    predicted_keys = first_prediction["cases"][0]["classifications"][0][
        "event_keys"
    ]

    replay = run_gold_baseline(
        provider=SequenceAIProvider([]),
        gold_path=gold_path,
        freeze_path=freeze_path,
        output_dir=output_dir,
    )

    assert predicted_keys == ["predicted-event-001", "predicted-event-002"]
    assert json.loads(replay.prediction_path.read_text()) == first_prediction
    assert replay.model_calls == 0
    report = json.loads(replay.report_path.read_text())
    assert report["evaluation"]["event_memberships"]["score"] == 1
    assert report["evaluation"]["temporal_metrics"]["included"] is False
