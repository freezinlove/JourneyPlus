from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from journeyplus.evaluation.cli import main
from journeyplus.evaluation.evaluator import evaluate
from journeyplus.evaluation.schema import GoldDataset


def _dataset(label="STATUS_OPPORTUNITY", fact_value="Gold"):
    return {
        "schema_version": "2",
        "dataset_version": 1,
        "cases": [
            {
                "case_id": "case-1",
                "version": 1,
                "documents": [
                    {
                        "document_key": "doc-1",
                        "source_url": "https://example.com/1",
                        "normalized_body": "A direct match to Gold.",
                    }
                ],
                "classifications": [
                    {
                        "document_key": "doc-1",
                        "label": label,
                        "event_keys": (
                            ["event-1"] if label == "STATUS_OPPORTUNITY" else []
                        ),
                    }
                ],
                "relationships": [],
                "facts": [
                    {
                        "event_key": "event-1",
                        "field": "target_status",
                        "value": fact_value,
                        "evidence": [
                            {"document_key": "doc-1", "locator": "sentence 1"}
                        ],
                    }
                ],
            }
        ],
    }


def test_versioned_gold_schema_and_metrics_have_no_assumed_threshold() -> None:
    gold = GoldDataset.model_validate(_dataset())
    candidate = GoldDataset.model_validate(_dataset(fact_value="Platinum"))
    report = evaluate(gold, candidate, label="candidate").as_dict()
    assert report["document_labels"]["score"] == 1
    assert report["event_memberships"]["score"] == 1
    assert report["fact_values"]["score"] == 0
    assert report["thresholds"] is None


def test_document_label_and_event_membership_are_scored_separately() -> None:
    candidate_data = _dataset()
    candidate_data["cases"][0]["classifications"][0]["event_keys"] = ["event-2"]
    report = evaluate(
        GoldDataset.model_validate(_dataset()),
        GoldDataset.model_validate(candidate_data),
        label="candidate",
    ).as_dict()

    assert report["document_labels"]["score"] == 1
    assert report["event_memberships"]["score"] == 1
    assert report["event_grouping"]["f1"] == 0


def test_event_grouping_uses_membership_not_event_identifier() -> None:
    gold_data = _dataset()
    gold_case = gold_data["cases"][0]
    gold_case["documents"].append(
        {
            "document_key": "doc-2",
            "source_url": "https://example.com/2",
            "normalized_body": "Another report about the same match.",
        }
    )
    gold_case["classifications"].append(
        {
            "document_key": "doc-2",
            "label": "STATUS_OPPORTUNITY",
            "event_keys": ["event-1"],
        }
    )
    candidate_data = json.loads(json.dumps(gold_data))
    for classification in candidate_data["cases"][0]["classifications"]:
        classification["event_keys"] = ["unrelated-predicted-id"]

    report = evaluate(
        GoldDataset.model_validate(gold_data),
        GoldDataset.model_validate(candidate_data),
        label="candidate",
    ).as_dict()

    assert report["event_grouping"] == {
        "true_positive": 1,
        "false_positive": 0,
        "false_negative": 0,
        "true_negative": 0,
        "precision": 1,
        "recall": 1,
        "f1": 1,
    }


def test_event_grouping_reports_splits_and_merges() -> None:
    gold_data = _dataset()
    gold_case = gold_data["cases"][0]
    for number, event_key in ((2, "event-1"), (3, "event-2")):
        gold_case["documents"].append(
            {
                "document_key": f"doc-{number}",
                "source_url": f"https://example.com/{number}",
                "normalized_body": f"Report {number}.",
            }
        )
        gold_case["classifications"].append(
            {
                "document_key": f"doc-{number}",
                "label": "STATUS_OPPORTUNITY",
                "event_keys": [event_key],
            }
        )
    candidate_data = json.loads(json.dumps(gold_data))
    predicted = candidate_data["cases"][0]["classifications"]
    predicted[0]["event_keys"] = ["predicted-a"]
    predicted[1]["event_keys"] = ["predicted-b"]
    predicted[2]["event_keys"] = ["predicted-a"]

    report = evaluate(
        GoldDataset.model_validate(gold_data),
        GoldDataset.model_validate(candidate_data),
        label="candidate",
    ).as_dict()

    assert report["event_grouping"]["false_negative"] == 1
    assert report["event_grouping"]["false_positive"] == 1
    assert {item["kind"] for item in report["errors"]} == {
        "same_event_split",
        "different_events_merged",
    }


def test_event_grouping_aligns_multi_event_documents_by_cross_document_overlap() -> None:
    gold_data = _dataset()
    gold_case = gold_data["cases"][0]
    gold_case["classifications"][0]["event_keys"] = ["accor", "kenya"]
    gold_case["documents"].append(
        {
            "document_key": "doc-2",
            "source_url": "https://example.com/2",
            "normalized_body": "A second report about Kenya.",
        }
    )
    gold_case["classifications"].append(
        {
            "document_key": "doc-2",
            "label": "STATUS_OPPORTUNITY",
            "event_keys": ["kenya"],
        }
    )
    candidate_data = json.loads(json.dumps(gold_data))
    candidate_classifications = candidate_data["cases"][0]["classifications"]
    candidate_classifications[0]["event_keys"] = [
        "predicted-accor",
        "predicted-voucher",
        "predicted-kenya",
    ]
    candidate_classifications[1]["event_keys"] = ["predicted-kenya"]

    report = evaluate(
        GoldDataset.model_validate(gold_data),
        GoldDataset.model_validate(candidate_data),
        label="candidate",
    ).as_dict()

    assert report["event_memberships"]["score"] == 0.5
    assert report["event_grouping"]["true_positive"] == 1
    assert report["event_grouping"]["false_negative"] == 0
    assert report["event_grouping"]["false_positive"] == 0


def test_gold_schema_rejects_legacy_version() -> None:
    legacy = _dataset()
    legacy["schema_version"] = "1"

    with pytest.raises(ValidationError):
        GoldDataset.model_validate(legacy)


def test_evaluation_cli_compares_named_outputs(tmp_path, capsys) -> None:
    gold_path = tmp_path / "gold.json"
    current_path = tmp_path / "current.json"
    candidate_path = tmp_path / "candidate.json"
    gold_path.write_text(json.dumps(_dataset()))
    current_path.write_text(json.dumps(_dataset()))
    candidate_path.write_text(json.dumps(_dataset(label="NONE")))

    assert main(
        [
            str(gold_path),
            "--prediction",
            f"current={current_path}",
            "--prediction",
            f"candidate={candidate_path}",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert [report["label"] for report in output["reports"]] == [
        "current",
        "candidate",
    ]
    assert output["reports"][0]["document_labels"]["score"] == 1
    assert output["reports"][1]["document_labels"]["score"] == 0
