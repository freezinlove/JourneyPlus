from __future__ import annotations

from datetime import date

from sqlalchemy import select

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.automation.initialization import (
    PUBLIC_FEED_SOURCE_IDS,
    mark_initialization_audit,
    run_mail_detail_initialization,
    run_public_initialization_window,
)
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import CollectionRun
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.history import HistoricalFeedWindowAdapter
from journeyplus.sources.registry import seed_sources


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


class MailDetailAdapter:
    source_id = "status_services_mail"

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id="statusmatch-page:example.statusmatch.com:faq",
                discovered_url="https://example.statusmatch.com/faq",
                canonical_url="https://example.statusmatch.com/faq",
                title="Example StatusMatch FAQ",
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body="Ordinary StatusMatch FAQ record",
            content_type="text/plain",
        )


class NamedMailDetailAdapter(MailDetailAdapter):
    def __init__(self, name: str) -> None:
        self.name = name

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=f"statusmatch-page:{self.name}.statusmatch.com:faq",
                discovered_url=f"https://{self.name}.statusmatch.com/faq",
                canonical_url=f"https://{self.name}.statusmatch.com/faq",
                title=f"{self.name} StatusMatch FAQ",
                raw_metadata={
                    "document_role": "linked_statusmatch_page",
                    "refresh_on_discovery": True,
                },
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=f"Ordinary StatusMatch FAQ record for {self.name}",
            content_type="text/plain",
            metadata={"document_role": "linked_statusmatch_page"},
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

    mail_details = run_mail_detail_initialization(
        session_factory,
        provider,
        lambda _source_id: MailDetailAdapter(),
    )
    repeated_mail_details = run_mail_detail_initialization(
        session_factory,
        provider,
        lambda _source_id: MailDetailAdapter(),
    )

    assert mail_details.status == "AWAITING_AUDIT"
    assert mail_details.audit_status == "PENDING"
    assert repeated_mail_details.skipped
    mark_initialization_audit(
        session_factory,
        batch_key="initialization:mail-details",
        passed=True,
        notes="synthetic mail details audit passed",
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


def test_mail_initialization_processes_only_documents_in_current_discovery(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        stale = collect_manual(
            session,
            NamedMailDetailAdapter("deleted-message-project"),
            idempotency_key="stale-mail-project",
        )
    provider = SequenceAIProvider([_none("current mailbox page")])

    summary = run_mail_detail_initialization(
        session_factory,
        provider,
        lambda _source_id: NamedMailDetailAdapter("current-project"),
    )

    assert summary.status == "AWAITING_AUDIT"
    assert summary.documents_selected == 1
    assert summary.backlog_count == 0
    assert len(provider.calls) == 1
    assert len(summary.sources[0].document_version_ids) == 1
    assert (
        stale.current_document_version_ids[0]
        not in summary.sources[0].document_version_ids
    )


def test_failed_mail_initialization_recollects_the_next_attempt(
    session_factory,
) -> None:
    first_provider = SequenceAIProvider(
        [
            {
                "label": "STATUS_OPPORTUNITY",
                "confidence": 0.99,
                "reason": "direct match",
                "event_hints": [
                    {
                        "program": "First Project",
                        "summary": "First Project status match",
                    }
                ],
            },
            ValueError("bad fact output"),
            ValueError("bad fact output"),
        ]
    )
    first = run_mail_detail_initialization(
        session_factory,
        first_provider,
        lambda _source_id: NamedMailDetailAdapter("first-project"),
    )
    second_provider = SequenceAIProvider([_none("second current page")])
    second = run_mail_detail_initialization(
        session_factory,
        second_provider,
        lambda _source_id: NamedMailDetailAdapter("second-project"),
    )

    assert first.status == "FAILED"
    assert second.status == "AWAITING_AUDIT"
    assert second.documents_selected == 1
    assert len(second_provider.calls) == 1
    with session_factory() as session:
        keys = set(session.scalars(select(CollectionRun.idempotency_key)))
    assert any(
        key.endswith(":attempt:1:status_services_mail") for key in keys
    )
    assert any(
        key.endswith(":attempt:2:status_services_mail") for key in keys
    )
