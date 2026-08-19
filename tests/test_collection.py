from __future__ import annotations

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.cli import build_parser
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources


class OneItemAdapter:
    source_id = "ffb_elite_status_feed"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="one",
                discovered_url="https://example.com/one",
                canonical_url="https://example.com/one",
                title="One",
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body="<p>Status match</p>",
        )


def test_manual_collection_is_idempotent_with_explicit_key(db_session) -> None:
    seed_sources(db_session)
    first = collect_manual(db_session, OneItemAdapter(), idempotency_key="manual:test")
    second = collect_manual(db_session, OneItemAdapter(), idempotency_key="manual:test")
    assert first.run_id == second.run_id
    assert first.new_versions == second.new_versions == 1


def test_manual_collection_cli_has_no_scheduler_command() -> None:
    args = build_parser().parse_args(["collect", "ffb_elite_status_feed"])
    assert args.command == "collect"
