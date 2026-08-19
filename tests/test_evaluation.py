from __future__ import annotations

import json

from journeyplus.evaluation.cli import main
from journeyplus.evaluation.evaluator import evaluate
from journeyplus.evaluation.schema import GoldDataset


def _dataset(label="YES", fact_value="Gold"):
    return {
        "schema_version": "1",
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
                "relevance": [
                    {"document_key": "doc-1", "label": label, "event_keys": ["event-1"]}
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
    assert report["relevance"]["score"] == 1
    assert report["fact_values"]["score"] == 0
    assert report["thresholds"] is None


def test_evaluation_cli_compares_named_outputs(tmp_path, capsys) -> None:
    gold_path = tmp_path / "gold.json"
    current_path = tmp_path / "current.json"
    candidate_path = tmp_path / "candidate.json"
    gold_path.write_text(json.dumps(_dataset()))
    current_path.write_text(json.dumps(_dataset()))
    candidate_path.write_text(json.dumps(_dataset(label="NO")))

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
    assert output["reports"][0]["relevance"]["score"] == 1
    assert output["reports"][1]["relevance"]["score"] == 0

