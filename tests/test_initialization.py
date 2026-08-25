from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.automation.initialization import (
    PUBLIC_FEED_SOURCE_IDS,
    mark_initialization_audit,
    run_mail_detail_initialization,
    run_public_initialization_window,
)
from journeyplus.contracts import Brief, DiscoveredItem, RawDocument
from journeyplus.models import (
    AnalysisRun,
    CollectionRun,
    InitializationRun,
    StatusMatchArticleRoute,
    StatusMatchArticleSupplement,
)
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.feed import FeedAdapter
from journeyplus.sources.history import HistoricalFeedWindowAdapter
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction


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
                external_id=(
                    f"statusmatch-page:{self.name}.statusmatch.com:{page_kind}"
                ),
                discovered_url=url,
                canonical_url=url,
                title=f"{self.name} StatusMatch {page_kind}",
                raw_metadata={
                    "document_role": "linked_statusmatch_page",
                    "managed_statusmatch_snapshot": True,
                    "project_host": f"{self.name}.statusmatch.com",
                    "page_kind": page_kind,
                    "refresh_on_discovery": True,
                },
            )
            for page_kind, url in (
                ("activity", f"https://{self.name}.statusmatch.com/"),
                ("faq", f"https://{self.name}.statusmatch.com/faq"),
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=(
                "<html><body><h1>Apply for a Status Match today</h1>"
                "<form><button>Continue</button></form></body></html>"
                if item.raw_metadata["page_kind"] == "activity"
                else "<html><body><h1>Frequently Asked Questions</h1>"
                "<p>The match is open.</p></body></html>"
            ),
            content_type="text/html",
            metadata={"document_role": "linked_statusmatch_page"},
        )


class InitializationProjectProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="initialization-statusmatch",
        region="local",
        config_version="initialization-statusmatch-v1",
    )

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, output_model
    ):
        request = json.loads(user_prompt)
        self.calls.append(output_model.__name__)
        if output_model is StatusMatchProjectExtraction:
            host = request["project_host"]
            return output_model.model_validate(
                {
                    "identity": {
                        "program": host.split(".", 1)[0],
                        "summary": f"{host} status match",
                    },
                    "what_happened": {
                        "value": "Current status-match applications are open",
                        "evidence": [
                            {"source": "HOME", "locator": "application heading"}
                        ],
                    },
                    "action_link": {
                        "value": f"https://{host}/",
                        "evidence": [
                            {"source": "HOME", "locator": "application form"}
                        ],
                    },
                }
            )
        if output_model is Brief:
            return output_model.model_validate(
                {
                    "fact_set_id": request["fact_set_id"],
                    "title": "当前会籍匹配开放申请",
                    "title_fact_keys": ["what_happened"],
                    "summary": "当前项目正在接受会籍匹配申请。",
                    "summary_fact_keys": ["what_happened"],
                    "key_points": [],
                    "caveats": [],
                    "source_links": request["allowed_source_links"],
                }
            )
        raise AssertionError(f"Unexpected output model: {output_model}")


class InitializationArticleProvider(InitializationProjectProvider):
    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, output_model
    ):
        if output_model.__name__ == "StatusMatchArticleExtraction":
            self.calls.append(output_model.__name__)
            return output_model.model_validate(
                {
                    "highlights": [
                        {
                            "kind": "FACTUAL_DETAIL",
                            "text": "文章额外说明申请获批后会显示数字会籍卡。",
                            "article_quote": (
                                "Approved members receive a digital membership card."
                            ),
                            "novelty_reason": (
                                "当前官方 FactSet 与简报均未提及数字会籍卡。"
                            ),
                        }
                    ]
                }
            )
        if output_model.__name__ == "RelevanceResult":
            self.calls.append(output_model.__name__)
            return output_model.model_validate(_none("ordinary initialization item"))
        return super().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
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
    provider = InitializationProjectProvider()

    summary = run_mail_detail_initialization(
        session_factory,
        provider,
        lambda _source_id: NamedMailDetailAdapter("current-project"),
    )

    assert summary.status == "AWAITING_AUDIT"
    assert summary.documents_selected == 1
    assert summary.backlog_count == 0
    assert len(provider.calls) == 2
    assert len(summary.sources[0].document_version_ids) == 2
    assert (
        stale.current_document_version_ids[0]
        not in summary.sources[0].document_version_ids
    )


def test_public_initialization_routes_linked_article_before_generic_documents(
    session_factory,
) -> None:
    host = "initialization-article.statusmatch.com"
    with session_factory.begin() as session:
        seed_sources(session)
        session.add(
            InitializationRun(
                batch_key="initialization:mail-details",
                batch_type="MAIL_DETAILS",
                status="PASSED",
                audit_status="PASSED",
            )
        )

    def feed_factory(source_id: str):
        base = f"https://example.com/{source_id}/feed/"
        body = (
            f'<a href="https://{host}/">official project</a>'
            "<p>Approved members receive a digital membership card.</p>"
            if source_id == "loyaltylobby_feed"
            else f"Ordinary historical news {source_id}"
        )
        xml = f"""<?xml version='1.0'?><rss version='2.0'><channel>
        <item><title>{source_id}-inside</title>
        <link>https://example.com/{source_id}-inside</link>
        <guid>{source_id}-inside</guid>
        <pubDate>Wed, 15 Jul 2026 00:00:00 +0000</pubDate>
        <description><![CDATA[{body}]]></description></item>
        <item><title>{source_id}-older</title>
        <link>https://example.com/{source_id}-older</link>
        <guid>{source_id}-older</guid>
        <pubDate>Tue, 14 Jul 2026 00:00:00 +0000</pubDate>
        <description><![CDATA[older]]></description></item>
        </channel></rss>"""
        return FeedAdapter(
            source_id=source_id,
            feed_url=base,
            content_strategy="feed_body_only",
            fetcher=MappingFetcher({base: xml}),
        )

    class StatusPageFetcher:
        def get(self, url: str) -> FetchResponse:
            body = (
                "<html><body><h1>Apply for a Status Match today</h1>"
                "<form><input type='text'><button>Continue</button></form>"
                "</body></html>"
                if not url.endswith("/faq")
                else "<html><body><h1>FAQ</h1><p>Applications are open.</p></body></html>"
            )
            return FetchResponse(body=body, content_type="text/html", final_url=url)

    provider = InitializationArticleProvider()
    summary = run_public_initialization_window(
        session_factory,
        provider,
        feed_factory,
        start=date(2026, 7, 15),
        end=date(2026, 7, 16),
        statusmatch_fetcher=StatusPageFetcher(),
    )

    assert summary.status == "AWAITING_AUDIT"
    assert summary.backlog_count == 0
    assert summary.documents_selected == 6
    assert provider.calls.count("StatusMatchProjectExtraction") == 1
    assert provider.calls.count("Brief") == 1
    assert provider.calls.count("StatusMatchArticleExtraction") == 1
    assert provider.calls.count("RelevanceResult") == 4
    with session_factory() as session:
        route = session.scalar(select(StatusMatchArticleRoute))
        assert route is not None and route.project_host == host
        assert session.scalar(select(StatusMatchArticleSupplement)) is not None
        assert not list(
            session.scalars(
                select(AnalysisRun).where(
                    AnalysisRun.document_version_id == route.document_version_id,
                    AnalysisRun.stage.in_(
                        (
                            "STATUS_RELEVANCE",
                            "EVENT_RELATIONSHIP",
                            "FACT_CONSOLIDATION",
                            "BRIEF_GENERATION",
                        )
                    ),
                )
            )
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
    second_provider = InitializationProjectProvider()
    second = run_mail_detail_initialization(
        session_factory,
        second_provider,
        lambda _source_id: NamedMailDetailAdapter("second-project"),
    )

    assert first.status == "FAILED"
    assert second.status == "AWAITING_AUDIT"
    assert second.documents_selected == 1
    assert len(second_provider.calls) == 2
    with session_factory() as session:
        keys = set(session.scalars(select(CollectionRun.idempotency_key)))
    assert any(
        key.endswith(":attempt:1:status_services_mail") for key in keys
    )
    assert any(
        key.endswith(":attempt:2:status_services_mail") for key in keys
    )
