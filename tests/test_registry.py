from __future__ import annotations

from journeyplus.sources.collection import automatically_scheduled_source_ids
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources


EXPECTED_IDS = {
    "ffb_elite_status_feed",
    "ffb_status_match_catalog",
    "awardwallet_elite_status_feed",
    "status_services_mail",
    "statusmatcher_reports",
    "loyaltylobby_feed",
    "frequentmiler_elite_status_feed",
    "verylvke_feed",
}


def test_registry_has_exactly_eight_stable_sources_and_no_cadence(db_session) -> None:
    assert {item.source_id for item in SOURCE_REGISTRY} == EXPECTED_IDS
    assert all(item.collection_cadence is None for item in SOURCE_REGISTRY)
    assert all(not item.automatic_scheduling for item in SOURCE_REGISTRY)

    first = seed_sources(db_session)
    second = seed_sources(db_session)
    assert len(first) == len(second) == 8
    assert automatically_scheduled_source_ids(db_session) == []


def test_mail_registry_contains_exact_intersection_without_sender_allowlist() -> None:
    mail = next(item for item in SOURCE_REGISTRY if item.source_id == "status_services_mail")
    assert mail.discovery_config["account"] == "kirikoomiku@gmail.com"
    assert mail.discovery_config["label"] == "statusmatch"
    assert mail.discovery_config["query"] == "to:(kirikoomiku+statusmatch@gmail.com)"
    assert mail.access_policy["sender_allowlist"] is None

