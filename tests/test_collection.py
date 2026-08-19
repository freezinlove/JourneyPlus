from __future__ import annotations

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.cli import build_parser
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources


class OneItemAdapter:
    source_id = "ffb_elite_status_feed"

    def __init__(self):
        self.fetch_count = 0

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="one",
                discovered_url="https://example.com/one",
                canonical_url="https://example.com/one",
                title="One",
                discovery_fingerprint="unchanged",
            )
        ]

    def fetch(self, item):
        self.fetch_count += 1
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body="<p>Status match</p>",
        )


def test_manual_collection_is_idempotent_with_explicit_key(db_session) -> None:
    seed_sources(db_session)
    adapter = OneItemAdapter()
    first = collect_manual(db_session, adapter, idempotency_key="manual:test")
    second = collect_manual(db_session, adapter, idempotency_key="manual:test")
    assert first.run_id == second.run_id
    assert first.new_versions == second.new_versions == 1


def test_new_collection_run_skips_unchanged_item_before_body_fetch(db_session) -> None:
    seed_sources(db_session)
    adapter = OneItemAdapter()
    collect_manual(db_session, adapter, idempotency_key="manual:first")
    second = collect_manual(db_session, adapter, idempotency_key="manual:second")
    assert adapter.fetch_count == 1
    assert second.discovered == 1
    assert second.new_versions == 0


def test_manual_collection_cli_has_no_scheduler_command() -> None:
    args = build_parser().parse_args(["collect", "ffb_elite_status_feed"])
    assert args.command == "collect"


def test_gmail_authorization_has_a_dedicated_cli_command() -> None:
    args = build_parser().parse_args(["gmail-authorize"])
    assert args.command == "gmail-authorize"


def test_ai_smoke_has_a_dedicated_cli_command() -> None:
    args = build_parser().parse_args(["ai-smoke"])
    assert args.command == "ai-smoke"
