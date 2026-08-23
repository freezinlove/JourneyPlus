from __future__ import annotations

from datetime import date

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.automation.initialization import (
    PUBLIC_FEED_SOURCE_IDS,
    mark_initialization_audit,
    run_catalog_initialization,
    run_public_initialization_window,
)
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.history import HistoricalFeedWindowAdapter


class MappingFetcher:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        return FetchResponse(
            body=self._responses[url],
            content_type="application/rss+xml",
            final_url=url,
        )


class CatalogAdapter:
    source_id = "ffb_status_match_catalog"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="catalog-one",
                discovered_url="https://example.com/catalog",
                canonical_url="https://example.com/catalog-one",
                title="Catalog one",
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body="Ordinary catalog record",
            content_type="text/plain",
        )


def _feed_xml(entries: list[tuple[str, str]]) -> str:
    items = "".join(
        f"""
        <item>
          <title>{identifier}</title>
          <link>https://example.com/{identifier}</link>
          <guid>{identifier}</guid>
          <pubDate>{published}</pubDate>
          <description><![CDATA[Ordinary historical news {identifier}]]></description>
        </item>
        """
        for identifier, published in entries
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{items}</channel></rss>"


def _none(reason: str = "not a status opportunity") -> dict:
    return {
        "label": "NONE",
        "confidence": 0.99,
        "reason": reason,
        "event_hints": [],
    }


def test_historical_feed_paginates_until_window_is_covered() -> None:
    base = "https://example.com/feed/"
    fetcher = MappingFetcher(
        {
            base: _feed_xml(
                [
                    ("newer", "Fri, 17 Jul 2026 00:00:00 +0000"),
                    ("inside-16", "Thu, 16 Jul 2026 00:00:00 +0000"),
                ]
            ),
            f"{base}?paged=2": _feed_xml(
                [
                    ("inside-15", "Wed, 15 Jul 2026 00:00:00 +0000"),
                    ("older", "Tue, 14 Jul 2026 00:00:00 +0000"),
                ]
            ),
        }
    )
    adapter = HistoricalFeedWindowAdapter(
        FeedAdapter(
            source_id="ffb_elite_status_feed",
            feed_url=base,
            content_strategy="feed_body_only",
            fetcher=fetcher,
        ),
        start=date(2026, 7, 15),
        end=date(2026, 7, 16),
    )

    items = adapter.discover()

    assert [item.external_id for item in items] == ["inside-15", "inside-16"]
    assert adapter.report is not None
    assert adapter.report.pages_scanned == 2
    assert adapter.report.eligible == 2


def test_initialization_requires_audit_before_next_batch(session_factory) -> None:
    provider = SequenceAIProvider([_none() for _ in range(20)])

    catalog = run_catalog_initialization(
        session_factory,
        provider,
        lambda _source_id: CatalogAdapter(),
    )
    repeated_catalog = run_catalog_initialization(
        session_factory,
        provider,
        lambda _source_id: CatalogAdapter(),
    )

    assert catalog.status == "AWAITING_AUDIT"
    assert catalog.audit_status == "PENDING"
    assert repeated_catalog.skipped
    mark_initialization_audit(
        session_factory,
        batch_key="initialization:catalog",
        passed=True,
        notes="synthetic catalog audit passed",
    )

    def feed_factory(source_id: str):
        base = f"https://example.com/{source_id}/feed/"
        return FeedAdapter(
            source_id=source_id,
            feed_url=base,
            content_strategy="feed_body_only",
            fetcher=MappingFetcher(
                {
                    base: _feed_xml(
                        [
                            (
                                f"{source_id}-inside",
                                "Wed, 15 Jul 2026 00:00:00 +0000",
                            ),
                            (
                                f"{source_id}-older",
                                "Tue, 14 Jul 2026 00:00:00 +0000",
                            ),
                        ]
                    )
                }
            ),
        )

    first = run_public_initialization_window(
        session_factory,
        provider,
        feed_factory,
        start=date(2026, 7, 15),
        end=date(2026, 7, 16),
    )
    blocked_next = run_public_initialization_window(
        session_factory,
        provider,
        feed_factory,
        start=date(2026, 7, 17),
        end=date(2026, 7, 18),
    )

    assert first.status == "AWAITING_AUDIT"
    assert {item.source_id for item in first.sources} == set(PUBLIC_FEED_SOURCE_IDS)
    assert blocked_next.status == "FAILED"
    assert "has not passed audit" in (blocked_next.error or "")

    mark_initialization_audit(
        session_factory,
        batch_key="initialization:2026-07-15:2026-07-16",
        passed=True,
        notes="synthetic first window audit passed",
    )
    second = run_public_initialization_window(
        session_factory,
        provider,
        feed_factory,
        start=date(2026, 7, 17),
        end=date(2026, 7, 18),
    )
    assert second.status == "AWAITING_AUDIT"
