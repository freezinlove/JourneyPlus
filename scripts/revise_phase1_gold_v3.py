from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from journeyplus.evaluation.schema import GoldDataset


ROOT = Path(__file__).resolve().parents[1]
V2_PATH = ROOT / "gold" / "status_opportunity_phase1_v2.json"
V2_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v2.freeze.json"
V3_PATH = ROOT / "gold" / "status_opportunity_phase1_v3.json"
V3_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v3.freeze.json"

IPREFER = "verylvke_feed:2026:08:03:iprefer-titanium-status-match-scandic-avios"
ACCOR_KENYA = (
    "verylvke_feed:2026:08:05:accor-all-plus-sale-kenya-airways-status-match"
)


def main() -> None:
    v2_freeze = json.loads(V2_FREEZE_PATH.read_text(encoding="utf-8"))
    v2_bytes = V2_PATH.read_bytes()
    if hashlib.sha256(v2_bytes).hexdigest() != v2_freeze["sha256"]:
        raise ValueError("v2 gold no longer matches its freeze manifest")

    payload = deepcopy(json.loads(v2_bytes))
    if payload["dataset_version"] != 2:
        raise ValueError("expected phase1 dataset version 2")
    payload["dataset_version"] = 3

    selected = _case(payload, "phase1-selected-articles")
    catalog = _case(payload, "phase1-ffb-status-match-catalog")
    if selected["version"] != 4 or catalog["version"] != 2:
        raise ValueError("unexpected v2 case versions")
    selected["version"] = 5
    selected["notes"] += (
        " v3按人工确认将iPrefer低价值混合攻略改为NONE，并把雅高混合文章"
        "标为等级房晚与Kenya Airways匹配两项会籍活动；正文、URL和时间边界不变。"
    )

    _replace_classification(
        selected,
        IPREFER,
        expected_label="STATUS_OPPORTUNITY",
        expected_event_keys=["iprefer-rewards-email-status-match-2026"],
        label="NONE",
        event_keys=[],
    )
    _replace_classification(
        selected,
        ACCOR_KENYA,
        expected_label="STATUS_OPPORTUNITY",
        expected_event_keys=[
            "kenya-airways-asante-rewards-paid-status-match-2026"
        ],
        label="STATUS_OPPORTUNITY",
        event_keys=[
            "accor-plus-five-elite-night-credits-2026",
            "kenya-airways-asante-rewards-paid-status-match-2026",
        ],
    )

    dataset = GoldDataset.model_validate(payload)
    _assert_documents_unchanged(
        GoldDataset.model_validate_json(v2_bytes), dataset
    )
    serialized = dataset.model_dump_json(indent=2).encode("utf-8") + b"\n"
    V3_PATH.write_bytes(serialized)
    digest = hashlib.sha256(serialized).hexdigest()
    V3_FREEZE_PATH.write_text(
        json.dumps(
            {
                "freeze_schema_version": 1,
                "dataset_path": "gold/status_opportunity_phase1_v3.json",
                "schema_version": dataset.schema_version,
                "dataset_version": dataset.dataset_version,
                "frozen_on": "2026-08-21",
                "revision_of": {
                    "dataset_path": "gold/status_opportunity_phase1_v2.json",
                    "sha256": v2_freeze["sha256"],
                },
                "sha256": digest,
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
                    "iPrefer混合攻略改为NONE",
                    "雅高混合文章标注等级房晚与Kenya Airways两项活动并排除五折房券",
                ],
                "temporal_policy": v2_freeze["temporal_policy"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {V3_PATH.relative_to(ROOT)} sha256={digest}")


def _case(payload: dict, case_id: str) -> dict:
    return next(case for case in payload["cases"] if case["case_id"] == case_id)


def _replace_classification(
    case: dict,
    document_key: str,
    *,
    expected_label: str,
    expected_event_keys: list[str],
    label: str,
    event_keys: list[str],
) -> None:
    classification = next(
        item
        for item in case["classifications"]
        if item["document_key"] == document_key
    )
    if (
        classification["label"] != expected_label
        or classification["event_keys"] != expected_event_keys
    ):
        raise ValueError(f"unexpected v2 classification for {document_key}")
    classification["label"] = label
    classification["event_keys"] = event_keys


def _assert_documents_unchanged(v2: GoldDataset, v3: GoldDataset) -> None:
    original = {
        document.document_key: (str(document.source_url), document.normalized_body)
        for case in v2.cases
        for document in case.documents
    }
    revised = {
        document.document_key: (str(document.source_url), document.normalized_body)
        for case in v3.cases
        for document in case.documents
    }
    if original != revised:
        raise ValueError("v3 must reuse every v2 URL and normalized body unchanged")


if __name__ == "__main__":
    main()
