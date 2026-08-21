from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from journeyplus.evaluation.schema import GoldDataset


ROOT = Path(__file__).parents[1]
GOLD_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.json"
FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.freeze.json"


def test_phase1_gold_matches_freeze_manifest() -> None:
    manifest = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    payload = GOLD_PATH.read_bytes()
    dataset = GoldDataset.model_validate_json(payload)

    assert hashlib.sha256(payload).hexdigest() == manifest["sha256"]
    assert dataset.schema_version == manifest["schema_version"]
    assert dataset.dataset_version == manifest["dataset_version"]
    assert {case.case_id: case.version for case in dataset.cases} == manifest[
        "case_versions"
    ]

    labels = Counter(
        classification.label.value
        for case in dataset.cases
        for classification in case.classifications
    )
    assert sum(len(case.documents) for case in dataset.cases) == manifest["counts"][
        "documents"
    ]
    assert labels == {
        "STATUS_OPPORTUNITY": manifest["counts"]["status_opportunity"],
        "NONE": manifest["counts"]["none"],
    }
    assert manifest["counts"]["uncertain"] == 0
    assert manifest["temporal_policy"][
        "classification_ignores_current_validity"
    ]
