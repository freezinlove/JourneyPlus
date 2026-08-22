from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from journeyplus.evaluation.schema import GoldDataset


ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.json"
V1_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.freeze.json"
V2_PATH = ROOT / "gold" / "status_opportunity_phase1_v2.json"
V2_FREEZE_PATH = ROOT / "gold" / "status_opportunity_phase1_v2.freeze.json"

IHG_MAX_5 = (
    "loyaltylobby_feed:2026:08:08:"
    "update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026"
)
IHG_MAX_10 = (
    "frequentmiler_elite_status_feed:"
    "targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights"
)
FLYING_BLUE_BA = (
    "ffb_status_match_catalog:flying-blue-ba-uk-paid-status-match-2026"
)


def main() -> None:
    v1_freeze = json.loads(V1_FREEZE_PATH.read_text(encoding="utf-8"))
    v1_bytes = V1_PATH.read_bytes()
    if hashlib.sha256(v1_bytes).hexdigest() != v1_freeze["sha256"]:
        raise ValueError("v1 gold no longer matches its freeze manifest")

    payload = deepcopy(json.loads(v1_bytes))
    if payload["dataset_version"] != 1:
        raise ValueError("expected phase1 dataset version 1")
    payload["dataset_version"] = 2

    selected = _case(payload, "phase1-selected-articles")
    catalog = _case(payload, "phase1-ffb-status-match-catalog")
    if selected["version"] != 3 or catalog["version"] != 1:
        raise ValueError("unexpected v1 case versions")
    selected["version"] = 4
    catalog["version"] = 2
    selected["notes"] += (
        " v2按人工确认把两项限时双倍精英房晚促销纳入会籍机会，"
        "正文、URL和时间边界不变。"
    )
    catalog["notes"] += (
        " v2按人工确认把Flying Blue英国入口与通用入口归为同一现实活动，"
        "正文和URL不变。"
    )

    _replace_classification(
        selected,
        IHG_MAX_5,
        expected_label="NONE",
        expected_event_keys=[],
        label="STATUS_OPPORTUNITY",
        event_keys=["ihg-double-elite-night-credits-max-5-2026"],
    )
    _replace_classification(
        selected,
        IHG_MAX_10,
        expected_label="NONE",
        expected_event_keys=[],
        label="STATUS_OPPORTUNITY",
        event_keys=["ihg-corporate-double-elite-night-credits-max-10-2026"],
    )
    _replace_classification(
        catalog,
        FLYING_BLUE_BA,
        expected_label="STATUS_OPPORTUNITY",
        expected_event_keys=["flying-blue-ba-uk-paid-status-match-2026"],
        label="STATUS_OPPORTUNITY",
        event_keys=["flying-blue-paid-status-match-2026"],
    )

    dataset = GoldDataset.model_validate(payload)
    _assert_documents_unchanged(
        GoldDataset.model_validate_json(v1_bytes), dataset
    )
    serialized = dataset.model_dump_json(indent=2).encode("utf-8") + b"\n"
    V2_PATH.write_bytes(serialized)
    digest = hashlib.sha256(serialized).hexdigest()
    V2_FREEZE_PATH.write_text(
        json.dumps(
            {
                "freeze_schema_version": 1,
                "dataset_path": "gold/status_opportunity_phase1_v2.json",
                "schema_version": dataset.schema_version,
                "dataset_version": dataset.dataset_version,
                "frozen_on": "2026-08-21",
                "revision_of": {
                    "dataset_path": "gold/status_opportunity_phase1_v1.json",
                    "sha256": v1_freeze["sha256"],
                },
                "sha256": digest,
                "case_versions": {
                    case.case_id: case.version for case in dataset.cases
                },
                "counts": {
                    "documents": 65,
                    "status_opportunity": 51,
                    "none": 14,
                    "uncertain": 0,
                },
                "scope": {
                    "statusmatcher_included": False,
                    "relationships_included": False,
                    "facts_included": False,
                    "documents_refetched": False,
                },
                "corrections": [
                    "两项限时双倍精英房晚促销改为STATUS_OPPORTUNITY并保持两个独立活动",
                    "Flying Blue英国BA Club入口与通用入口使用同一活动键",
                ],
                "temporal_policy": v1_freeze["temporal_policy"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {V2_PATH.relative_to(ROOT)} sha256={digest}")


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
        raise ValueError(f"unexpected v1 classification for {document_key}")
    classification["label"] = label
    classification["event_keys"] = event_keys


def _assert_documents_unchanged(v1: GoldDataset, v2: GoldDataset) -> None:
    original = {
        document.document_key: (
            str(document.source_url),
            document.normalized_body,
        )
        for case in v1.cases
        for document in case.documents
    }
    revised = {
        document.document_key: (
            str(document.source_url),
            document.normalized_body,
        )
        for case in v2.cases
        for document in case.documents
    }
    if original != revised:
        raise ValueError("v2 must reuse every v1 URL and normalized body unchanged")


if __name__ == "__main__":
    main()
