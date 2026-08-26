from __future__ import annotations

import journeyplus.cli as cli
import pytest
from sqlalchemy import select

from journeyplus.config import Settings
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.cli import build_parser
from journeyplus.models import SourceAutomationState, SourceItem
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.registry import seed_sources
from journeyplus.sources.single_page import SinglePageAdapter


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
    assert first.new_versions == 1
    assert second.new_versions == 0
    assert first.reused_run is False
    assert second.reused_run is True
    assert len(first.document_version_ids) == 1
    assert first.current_document_version_ids == first.document_version_ids
    assert second.document_version_ids == ()
    assert second.current_document_version_ids == ()


def test_new_collection_run_skips_unchanged_item_before_body_fetch(db_session) -> None:
    seed_sources(db_session)
    adapter = OneItemAdapter()
    collect_manual(db_session, adapter, idempotency_key="manual:first")
    second = collect_manual(db_session, adapter, idempotency_key="manual:second")
    assert adapter.fetch_count == 1
    assert second.discovered == 1
    assert second.new_versions == 0
    assert len(second.current_document_version_ids) == 1


def test_refreshable_linked_page_is_refetched_but_only_versions_changes(
    db_session,
) -> None:
    class RefreshingPageAdapter(OneItemAdapter):
        source_id = "status_services_mail"

        def __init__(self):
            super().__init__()
            self.body = "<p>Version one</p>"

        def discover(self):
            return [
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id="statusmatch-page:example.statusmatch.com:faq",
                    discovered_url="https://example.statusmatch.com/faq",
                    canonical_url="https://example.statusmatch.com/faq",
                    raw_metadata={"refresh_on_discovery": True},
                )
            ]

        def fetch(self, item):
            self.fetch_count += 1
            return RawDocument(
                source_id=self.source_id,
                external_id=item.external_id,
                canonical_url=item.canonical_url,
                body=self.body,
            )

    seed_sources(db_session)
    adapter = RefreshingPageAdapter()
    first = collect_manual(db_session, adapter, idempotency_key="refresh:first")
    unchanged = collect_manual(db_session, adapter, idempotency_key="refresh:second")
    adapter.body = "<p>Version two</p>"
    changed = collect_manual(db_session, adapter, idempotency_key="refresh:third")

    assert first.new_versions == 1
    assert unchanged.new_versions == 0
    assert changed.new_versions == 1
    assert adapter.fetch_count == 3


def test_single_page_collection_refetches_but_versions_only_content_changes(
    db_session,
) -> None:
    class MutableFetcher:
        def __init__(self) -> None:
            self.body = "<html><article>Version one</article></html>"
            self.calls = 0

        def get(self, url: str) -> FetchResponse:
            self.calls += 1
            return FetchResponse(
                body=self.body,
                content_type="text/html",
                final_url=url,
            )

    seed_sources(db_session)
    fetcher = MutableFetcher()
    adapter = SinglePageAdapter(
        source_id="awardwallet_buy_points_page",
        page_url=(
            "https://awardwallet.com/news/"
            "current-promotions-buy-points-miles/"
        ),
        external_id="current-promotions-buy-points-miles",
        content_strategy="fetch_article",
        fetcher=fetcher,
    )

    first = collect_manual(db_session, adapter, idempotency_key="buy:first")
    unchanged = collect_manual(db_session, adapter, idempotency_key="buy:second")
    fetcher.body = "<html><article>Version two</article></html>"
    changed = collect_manual(db_session, adapter, idempotency_key="buy:third")

    assert first.new_versions == 1
    assert unchanged.new_versions == 0
    assert changed.new_versions == 1
    assert fetcher.calls == 3


def test_manual_collection_can_limit_fetched_items(db_session) -> None:
    class ThreeItemAdapter(OneItemAdapter):
        def discover(self):
            return [
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id=str(index),
                    discovered_url=f"https://example.com/{index}",
                    canonical_url=f"https://example.com/{index}",
                    title=str(index),
                    discovery_fingerprint="unchanged",
                )
                for index in range(3)
            ]

    seed_sources(db_session)
    adapter = ThreeItemAdapter()
    summary = collect_manual(db_session, adapter, max_items=1)

    assert summary.discovered == 3
    assert summary.considered == 1
    assert summary.new_versions == 1
    assert adapter.fetch_count == 1


class PagedFeedFetcher:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        return FetchResponse(
            body=self.responses[url],
            content_type="application/rss+xml",
            final_url=url,
        )


def _feed_xml(entries: list[tuple[str, str]]) -> str:
    items = "".join(
        (
            "<item>"
            f"<guid>{external_id}</guid>"
            f"<link>https://example.com/{external_id}</link>"
            f"<title>{external_id}</title>"
            f"<pubDate>{published_at}</pubDate>"
            f"<description><![CDATA[<p>{external_id} body</p>]]></description>"
            "</item>"
        )
        for external_id, published_at in entries
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{items}</channel></rss>"


def _incremental_loyalty_adapter(fetcher: PagedFeedFetcher) -> FeedAdapter:
    return FeedAdapter(
        source_id="loyaltylobby_feed",
        feed_url="https://loyaltylobby.com/feed/",
        content_strategy="feed_body_only",
        fetcher=fetcher,
        incremental_baseline_date="2026-08-24",
        incremental_timezone="Asia/Shanghai",
        incremental_max_pages=5,
    )


def test_loyalty_incremental_cursor_advances_without_skipping_limited_items(
    db_session,
) -> None:
    seed_sources(db_session)
    first_fetcher = PagedFeedFetcher(
        {
            "https://loyaltylobby.com/feed/": _feed_xml(
                [
                    ("new-3", "Wed, 26 Aug 2026 02:00:00 +0000"),
                    ("new-2", "Tue, 25 Aug 2026 02:00:00 +0000"),
                ]
            ),
            "https://loyaltylobby.com/feed/?paged=2": _feed_xml(
                [
                    ("new-1", "Mon, 24 Aug 2026 16:00:00 +0000"),
                    ("baseline", "Mon, 24 Aug 2026 15:59:00 +0000"),
                ]
            ),
        }
    )

    first = collect_manual(
        db_session,
        _incremental_loyalty_adapter(first_fetcher),
        idempotency_key="loyalty:first-incremental",
        max_items=2,
    )

    state = db_session.get(SourceAutomationState, "loyaltylobby_feed")
    assert first.discovered == 3
    assert first.considered == 2
    assert state is not None
    assert state.discovery_cursor == "new-2"
    assert set(
        db_session.scalars(
            select(SourceItem.external_id).where(
                SourceItem.source_id == "loyaltylobby_feed"
            )
        )
    ) == {"new-1", "new-2"}

    second_fetcher = PagedFeedFetcher(
        {
            "https://loyaltylobby.com/feed/": _feed_xml(
                [
                    ("new-4", "Wed, 26 Aug 2026 03:00:00 +0000"),
                    ("new-3", "Wed, 26 Aug 2026 02:00:00 +0000"),
                    ("new-2", "Tue, 25 Aug 2026 02:00:00 +0000"),
                ]
            )
        }
    )
    second = collect_manual(
        db_session,
        _incremental_loyalty_adapter(second_fetcher),
        idempotency_key="loyalty:second-incremental",
        max_items=2,
    )

    assert second.discovered == 2
    assert second.considered == 2
    assert state.discovery_cursor == "new-4"
    assert set(
        db_session.scalars(
            select(SourceItem.external_id).where(
                SourceItem.source_id == "loyaltylobby_feed"
            )
        )
    ) == {"new-1", "new-2", "new-3", "new-4"}
    assert first_fetcher.calls == [
        "https://loyaltylobby.com/feed/",
        "https://loyaltylobby.com/feed/?paged=2",
    ]
    assert second_fetcher.calls == ["https://loyaltylobby.com/feed/"]


def test_manual_collection_cli_has_no_scheduler_command() -> None:
    args = build_parser().parse_args(["collect", "ffb_elite_status_feed"])
    assert args.command == "collect"


def test_gmail_authorization_has_a_dedicated_cli_command() -> None:
    args = build_parser().parse_args(["gmail-authorize"])
    assert args.command == "gmail-authorize"


def test_ai_smoke_has_a_dedicated_cli_command() -> None:
    args = build_parser().parse_args(["ai-smoke"])
    assert args.command == "ai-smoke"


def test_runtime_cli_keeps_collection_and_processing_separate() -> None:
    collect = build_parser().parse_args(
        ["collect", "status_services_mail", "--limit", "1"]
    )
    process = build_parser().parse_args(
        ["process-pending", "--source-id", "status_services_mail", "--limit", "1"]
    )
    run_source = build_parser().parse_args(
        ["run-source", "status_services_mail", "--limit", "1"]
    )

    assert collect.command == "collect"
    assert process.command == "process-pending"
    assert run_source.command == "run-source"


def test_ffb_catalog_is_not_a_cli_source_or_initialization_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["collect", "ffb_status_match_catalog"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["initialize-catalog"])
    assert (
        build_parser().parse_args(["initialize-mail-details"]).command
        == "initialize-mail-details"
    )


def test_gmail_authorization_does_not_initialize_database(
    monkeypatch, capsys
) -> None:
    settings = Settings()

    def fail_if_database_is_initialized(_settings):
        raise AssertionError("This command must not initialize the database")

    monkeypatch.setattr(
        cli.Settings, "from_env", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(cli, "engine_from_settings", fail_if_database_is_initialized)
    monkeypatch.setattr(
        cli, "authorize_gmail", lambda _settings: "kirikoomiku@gmail.com"
    )

    assert cli.main(["gmail-authorize"]) == 0
    assert "kirikoomiku@gmail.com" in capsys.readouterr().out


def test_ai_smoke_does_not_initialize_database(monkeypatch, capsys) -> None:
    class SmokeResult:
        @staticmethod
        def model_dump_json() -> str:
            return '{"ok":true,"message":"connected"}'

    def fail_if_database_is_initialized(_settings):
        raise AssertionError("This command must not initialize the database")

    settings = Settings()
    monkeypatch.setattr(
        cli.Settings, "from_env", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(cli, "engine_from_settings", fail_if_database_is_initialized)
    monkeypatch.setattr(cli, "run_ai_smoke", lambda _settings: SmokeResult())

    assert cli.main(["ai-smoke"]) == 0
    assert '"ok":true' in capsys.readouterr().out
