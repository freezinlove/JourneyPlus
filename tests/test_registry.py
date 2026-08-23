from __future__ import annotations

from journeyplus.models import Source
from journeyplus.sources.collection import automatically_scheduled_source_ids
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources


EXPECTED_IDS = {
    "ffb_elite_status_feed",
    "awardwallet_elite_status_feed",
    "status_services_mail",
    "loyaltylobby_feed",
    "frequentmiler_elite_status_feed",
    "verylvke_feed",
}


def test_registry_has_exactly_six_daily_sources_with_scheduling_off(db_session) -> None:
    assert {item.source_id for item in SOURCE_REGISTRY} == EXPECTED_IDS
    assert all(item.collection_cadence == "P1D" for item in SOURCE_REGISTRY)
    assert all(not item.automatic_scheduling for item in SOURCE_REGISTRY)
    assert all(item.enabled for item in SOURCE_REGISTRY)

    first = seed_sources(db_session)
    second = seed_sources(db_session)
    assert len(first) == len(second) == 6
    assert automatically_scheduled_source_ids(db_session) == []


def test_seeding_disables_a_retired_statusmatcher_record_without_deleting_it(
    db_session,
) -> None:
    retired = Source(
        id="statusmatcher_reports",
        name="Retired StatusMatcher",
        adapter_type="statusmatcher",
        discovery_config={},
        access_policy={},
        collection_cadence="PT1H",
        automatic_scheduling=True,
        enabled=True,
    )
    db_session.add(retired)
    db_session.flush()

    seeded = seed_sources(db_session)

    assert len(seeded) == 6
    assert db_session.get(Source, "statusmatcher_reports") is retired
    assert retired.enabled is False
    assert retired.automatic_scheduling is False
    assert retired.collection_cadence is None


def test_seeding_disables_retired_ffb_catalog_without_deleting_history(
    db_session,
) -> None:
    retired = Source(
        id="ffb_status_match_catalog",
        name="Retired FFB Catalog",
        adapter_type="static_catalog",
        discovery_config={},
        access_policy={},
        collection_cadence="P1D",
        automatic_scheduling=True,
        enabled=True,
    )
    db_session.add(retired)
    db_session.flush()

    seed_sources(db_session)

    assert db_session.get(Source, "ffb_status_match_catalog") is retired
    assert retired.enabled is False
    assert retired.automatic_scheduling is False
    assert retired.collection_cadence is None


def test_mail_registry_contains_exact_intersection_without_sender_allowlist() -> None:
    mail = next(item for item in SOURCE_REGISTRY if item.source_id == "status_services_mail")
    assert mail.discovery_config["account"] == "kirikoomiku@gmail.com"
    assert mail.discovery_config["label"] == "statusmatch"
    assert mail.discovery_config["query"] == "to:(kirikoomiku+statusmatch@gmail.com)"
    assert mail.access_policy["sender_allowlist"] is None
    assert mail.content_strategy == "message_body_and_linked_statusmatch_pages"
