from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from journeyplus.evaluation.schema import GoldDataset


ROOT = Path(__file__).resolve().parents[1]
V3_PATH = ROOT / "gold" / "status_opportunity_phase1_v3.json"
V3_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v3.freeze.json"
V4_PATH = ROOT / "gold" / "status_opportunity_phase1_v4.json"
V4_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v4.freeze.json"
EXPECTED_V3_SHA256 = (
    "9e6b1767cd63a6b92a9f242f030f32dedbcf262056cb625598339aaa3b70be69"
)
BEST_WESTERN_US = (
    "ffb_status_match_catalog:best-western-us-military-gold-direct-grant"
)
BEST_WESTERN_CANADA = (
    "ffb_status_match_catalog:best-western-canada-military-gold-direct-grant"
)
BEST_WESTERN_SERVICE_REWARDS = (
    "best-western-service-rewards-military-gold-direct-grant"
)


def main() -> None:
    v3_freeze = json.loads(V3_FREEZE_PATH.read_text(encoding="utf-8"))
    v3_bytes = V3_PATH.read_bytes()
    digest = hashlib.sha256(v3_bytes).hexdigest()
    if digest != EXPECTED_V3_SHA256 or v3_freeze["sha256"] != EXPECTED_V3_SHA256:
        raise ValueError("v3 gold no longer matches its frozen reviewed SHA-256")

    payload = deepcopy(json.loads(v3_bytes))
    if payload["dataset_version"] != 3:
        raise ValueError("expected phase1 dataset version 3")
    payload["dataset_version"] = 4

    selected = _case(payload, "phase1-selected-articles")
    catalog = _case(payload, "phase1-ffb-status-match-catalog")
    if selected["version"] != 5 or catalog["version"] != 2:
        raise ValueError("unexpected v3 case versions")
    catalog["version"] = 3
    catalog["notes"] += (
        " v4按人工确认将Best Western Service Rewards美国与加拿大军人"
        "Gold直授入口归为同一现实活动；全部正文、URL、标签和活动出现次数不变。"
    )

    _replace_event_key(
        catalog,
        BEST_WESTERN_US,
        expected="best-western-us-military-gold-direct-grant",
        replacement=BEST_WESTERN_SERVICE_REWARDS,
    )
    _replace_event_key(
        catalog,
        BEST_WESTERN_CANADA,
        expected="best-western-canada-military-gold-direct-grant",
        replacement=BEST_WESTERN_SERVICE_REWARDS,
    )

    v3 = GoldDataset.model_validate_json(v3_bytes)
    dataset = GoldDataset.model_validate(payload)
    _assert_documents_unchanged(v3, dataset)
    _assert_only_best_western_grouping_changed(v3, dataset)
    serialized = dataset.model_dump_json(indent=2).encode("utf-8") + b"\n"
    V4_PATH.write_bytes(serialized)
    v4_digest = hashlib.sha256(serialized).hexdigest()
    V4_FREEZE_PATH.write_text(
        json.dumps(
            {
                "freeze_schema_version": 1,
                "dataset_path": "gold/status_opportunity_phase1_v4.json",
                "schema_version": dataset.schema_version,
                "dataset_version": dataset.dataset_version,
                "frozen_on": "2026-08-22",
                "revision_of": {
                    "dataset_path": "gold/status_opportunity_phase1_v3.json",
                    "sha256": EXPECTED_V3_SHA256,
                },
                "sha256": v4_digest,
                "case_versions": {
                    case.case_id: case.version for case in dataset.cases
                },
                "counts": {
                    "documents": 65,
                    "status_opportunity": 50,
                    "none": 15,
                    "uncertain": 0,
                },
                "scope": {
                    "statusmatcher_included": False,
                    "relationships_included": False,
                    "facts_included": False,
                    "documents_refetched": False,
                },
                "corrections": [
                    "Best Western Service Rewards美国与加拿大军人Gold直授入口使用同一活动键"
                ],
                "temporal_policy": v3_freeze["temporal_policy"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {V4_PATH.relative_to(ROOT)} sha256={v4_digest}")


def _case(payload: dict, case_id: str) -> dict:
    return next(case for case in payload["cases"] if case["case_id"] == case_id)


def _replace_event_key(
    case: dict,
    document_key: str,
    *,
    expected: str,
    replacement: str,
) -> None:
    classification = next(
        item
        for item in case["classifications"]
        if item["document_key"] == document_key
    )
    if classification["label"] != "STATUS_OPPORTUNITY" or classification[
        "event_keys"
    ] != [expected]:
        raise ValueError(f"unexpected v3 classification for {document_key}")
    classification["event_keys"] = [replacement]


def _assert_documents_unchanged(v3: GoldDataset, v4: GoldDataset) -> None:
    original = {
        document.document_key: (str(document.source_url), document.normalized_body)
        for case in v3.cases
        for document in case.documents
    }
    revised = {
        document.document_key: (str(document.source_url), document.normalized_body)
        for case in v4.cases
        for document in case.documents
    }
    if original != revised:
        raise ValueError("v4 must reuse every v3 URL and normalized body unchanged")


def _assert_only_best_western_grouping_changed(
    v3: GoldDataset, v4: GoldDataset
) -> None:
    original = {
        item.document_key: item.model_dump(mode="json")
        for case in v3.cases
        for item in case.classifications
    }
    revised = {
        item.document_key: item.model_dump(mode="json")
        for case in v4.cases
        for item in case.classifications
    }
    changed = {
        key for key in original if original[key] != revised.get(key)
    }
    if changed != {BEST_WESTERN_US, BEST_WESTERN_CANADA}:
        raise ValueError("v4 may only change the two reviewed Best Western groupings")


if __name__ == "__main__":
    main()
