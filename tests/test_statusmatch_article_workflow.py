from __future__ import annotations

from sqlalchemy import func, select

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.automation.service import automation_status, run_daily_cycle
from journeyplus.cli import build_parser
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import (
    AnalysisRun,
    ArticleOpportunityRecord,
    BriefRecord,
    FactSetRecord,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchArticleSupplement,
    StatusMatchWatch,
)
from journeyplus.membership.contracts import MappingContributionSource
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.operations import pending_documents, process_pending_documents
from journeyplus.review.api import create_review_app
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.article_workflow import (
    process_pending_statusmatch_articles,
)
from journeyplus.statusmatch.articles import (
    discover_statusmatch_article_routes,
    prepare_statusmatch_article_projects,
    refresh_statusmatch_article_route_readiness,
)
from journeyplus.statusmatch.composed_brief import composed_statusmatch_brief
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch
from journeyplus.statusmatch.watchlist import delete_watch_only


ARTICLE_URL = "https://loyaltylobby.com/2026/08/03/example/"
HOST = "kenya-airways.statusmatch.com"


class ArticleAdapter:
    source_id = "loyaltylobby_feed"

    def __init__(self, *, linked: bool = True, external_id: str = "article") -> None:
        self.linked = linked
        self.external_id = external_id

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=self.external_id,
                discovered_url=ARTICLE_URL,
                canonical_url=ARTICLE_URL,
                title="Kenya Airways match",
                raw_metadata={"content_strategy": "feed_body_only"},
            )
        ]

    def fetch(self, item):
        link = (
            f'<a href="https://{HOST}/apply?utm_source=article">apply here</a>'
            if self.linked
            else "no project link"
        )
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=(
                "<article><p>Kenya Airways opens a match.</p>"
                "<p>This article adds a practical warning.</p>"
                f"<p>{link}</p></article>"
            ),
            content_type="text/html",
            metadata={
                "content_strategy": "feed_body_only",
                "title": item.title,
            },
        )


class PageFetcher:
    def __init__(self, *, closed: bool = False) -> None:
        self.closed = closed
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        body = (
            "<html><body><h1>Awaiting new offers</h1></body></html>"
            if self.closed
            else "<html><body><h1>Status Match</h1><p>Applications are open.</p></body></html>"
        )
        return FetchResponse(body=body, content_type="text/html", final_url=url)


class DailyArticleProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="daily-article",
        region="local",
        config_version="daily-article-v1",
    )

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_structured(self, *, system_prompt, user_prompt, output_model):
        import json

        request = json.loads(user_prompt)
        self.calls.append(output_model.__name__)
        if output_model.__name__ == "StatusMatchProjectExtraction":
            host = request["project_host"]
            return output_model.model_validate(
                {
                    "identity": {
                        "program": "Kenya Airways Asante Rewards",
                        "summary": "Kenya Airways status match",
                        "target_status": "Platinum Elite Plus",
                    },
                    "what_happened": {
                        "value": "Kenya Airways is accepting status matches",
                        "evidence": [{"source": "HOME", "locator": "open offer"}],
                    },
                    "action_link": {
                        "value": f"https://{host}/",
                        "evidence": [{"source": "HOME", "locator": "application"}],
                    },
                }
            )
        if output_model.__name__ == "Brief":
            return output_model.model_validate(
                {
                    "fact_set_id": request["fact_set_id"],
                    "title": "Kenya Airways 开放会籍匹配",
                    "title_fact_keys": ["what_happened"],
                    "summary": "Kenya Airways 正在接受会籍匹配。",
                    "summary_fact_keys": ["what_happened"],
                    "key_points": [],
                    "caveats": [],
                    "source_links": request["allowed_source_links"],
                }
            )
        if output_model.__name__ == "StatusMatchArticleExtraction":
            return output_model.model_validate(_highlight_response())
        raise AssertionError(f"unexpected model: {output_model.__name__}")


def _collect_article(session, *, linked: bool = True, external_id: str = "article"):
    seed_sources(session)
    return collect_manual(
        session,
        ArticleAdapter(linked=linked, external_id=external_id),
        idempotency_key=f"collect:{external_id}",
    )


def _seed_official_output(session):
    watch = ensure_statusmatch_watch(session, HOST)
    event = StatusEvent(
        created_from_key=f"statusmatch-watch:{watch.id}",
        program="Kenya Airways Asante Rewards",
        target_status="Platinum",
        summary="Kenya Airways matches eligible Accor members",
        search_text="Kenya Airways Accor status match",
    )
    session.add(event)
    session.flush()
    fact = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version="4",
        facts={
            "schema_version": "4",
            "what_happened": {"value": "Eligible Accor members can match", "evidence": []},
        },
    )
    session.add(fact)
    session.flush()
    brief = BriefRecord(
        fact_set_id=fact.id,
        version=1,
        schema_version="1",
        content={
            "schema_version": "1",
            "fact_set_id": str(fact.id),
            "title": "Kenya Airways 开放会籍匹配",
            "title_fact_keys": ["what_happened"],
            "summary": "Accor 会员可申请。",
            "summary_fact_keys": ["what_happened"],
            "key_points": [
                {
                    "text": "符合条件的 Accor 会员可以申请。",
                    "fact_keys": ["what_happened"],
                }
            ],
            "caveats": [],
            "source_links": [],
        },
    )
    session.add(brief)
    session.flush()
    event.current_fact_set_id = fact.id
    event.current_brief_id = brief.id
    watch.current_event_id = event.id
    watch.status = "ACTIVE"
    session.flush()
    return watch, event, fact, brief


def _highlight_response(
    highlight: str = "文章额外提醒了一项实际注意事项。",
):
    return {
        "schema_version": "3",
        "highlights": [highlight],
    }


def test_single_supplement_call_preserves_official_fact(
    session_factory,
) -> None:
    quote = (
        "Accor Live Limitless Gold members can match directly to Kenya Airways "
        "Asante Rewards Platinum."
    )

    class MappingArticleAdapter(ArticleAdapter):
        def fetch(self, item):
            return RawDocument(
                source_id=self.source_id,
                external_id=item.external_id,
                canonical_url=item.canonical_url,
                body=(
                    f"<article><p>{quote}</p>"
                    f'<a href="https://{HOST}/">apply</a></article>'
                ),
                content_type="text/html",
            )

    with session_factory.begin() as session:
        seed_sources(session)
        collection = collect_manual(session, MappingArticleAdapter())
        _watch, _event, fact, _brief = _seed_official_output(session)
        original_fact = dict(fact.facts)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
        fact_id = fact.id
    provider = SequenceAIProvider(
        [
            {
                "schema_version": "3",
                "highlights": [],
            }
        ]
    )

    result = process_pending_statusmatch_articles(session_factory, provider)

    assert result.succeeded == result.model_calls == 1
    assert result.routes[0].mapping_claim_count == 0
    assert result.routes[0].status == "NO_NOVEL_HIGHLIGHTS"
    with session_factory.begin() as session:
        supplement = session.scalar(select(StatusMatchArticleSupplement))
        assert supplement is not None
        assert supplement.mapping_claims == []
        assert session.scalar(
            select(func.count()).select_from(ArticleOpportunityRecord)
        ) == 0
        assert session.get(FactSetRecord, fact_id).facts == original_fact
        composed = composed_statusmatch_brief(session, host=HOST)
        assert composed.supplements == []
        supplement.mapping_claims = [
            {"status": "CANDIDATE", "legacy_id": "candidate"},
            {"status": "CONFLICTING", "legacy_id": "conflicting"},
            {"status": "APPROVED", "legacy_id": "approved"},
        ]
        session.flush()
        unified = UnifiedMembershipTreeService(session).audit()
        assert all(
            contribution.source == MappingContributionSource.STATUSMATCH_OFFICIAL
            for edge in unified.edges
            for contribution in edge.contributions
        )
        assert session.get(FactSetRecord, fact_id).facts == original_fact


def test_linked_article_routes_and_is_excluded_from_generic_workflow(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        discovery = discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )

    assert discovery.routes_created == 1
    assert discovery.project_hosts == (HOST,)
    with session_factory() as session:
        assert pending_documents(
            session, SequenceAIProvider([]), source_ids=["loyaltylobby_feed"]
        ) == []
        route = session.scalar(select(StatusMatchArticleRoute))
        assert route is not None and route.project_url == f"https://{HOST}/"


def test_unlinked_article_remains_on_generic_workflow(session_factory) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session, linked=False)
        discovery = discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
    assert discovery.routes_created == 0
    provider = SequenceAIProvider(
        [
            {
                "label": "NONE",
                "confidence": 0.99,
                "reason": "ordinary article",
                "event_hints": [],
            }
        ]
    )
    summary = process_pending_documents(session_factory, provider)
    assert summary.succeeded == 1
    assert len(provider.calls) == 1


def test_one_article_creates_independent_routes_for_multiple_hosts(
    session_factory,
) -> None:
    second_host = "flyingblue.statusmatch.com"

    class MultiHostArticle(ArticleAdapter):
        def fetch(self, item):
            return RawDocument(
                source_id=self.source_id,
                external_id=item.external_id,
                canonical_url=item.canonical_url,
                body=(
                    f'<a href="https://{HOST}/">Kenya</a>'
                    f'<a href="https://{HOST}/faq">Kenya FAQ duplicate</a>'
                    f'<a href="https://{second_host}/">Flying Blue</a>'
                ),
                content_type="text/html",
                metadata={
                    "content_strategy": "feed_body_only",
                    "title": item.title,
                },
            )

    with session_factory.begin() as session:
        seed_sources(session)
        collection = collect_manual(session, MultiHostArticle())
        discovery = discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )

    assert discovery.routes_created == 2
    assert discovery.project_hosts == (second_host, HOST)
    with session_factory() as session:
        assert set(session.scalars(select(StatusMatchArticleRoute.project_host))) == {
            HOST,
            second_host,
        }


def test_unknown_project_fetches_both_pages_and_closed_project_is_terminal(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        fetcher = PageFetcher(closed=True)
        summary = prepare_statusmatch_article_projects(session, fetcher)

    assert summary.watches_created == 1
    assert summary.hosts_fetched == (HOST,)
    assert len(fetcher.calls) == 2
    assert summary.closed_routes == 1
    with session_factory() as session:
        assert session.scalar(select(StatusMatchWatch)) is None
        route = session.scalar(select(StatusMatchArticleRoute))
        assert route is not None and route.status == "OFFICIAL_CLOSED"
        again = prepare_statusmatch_article_projects(session, PageFetcher())
        assert again.hosts_considered == 0


def test_existing_ready_project_is_not_fetched_because_article_appeared(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        _seed_official_output(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        fetcher = PageFetcher()
        summary = prepare_statusmatch_article_projects(session, fetcher)

    assert fetcher.calls == []
    assert summary.hosts_fetched == ()
    assert summary.ready_routes == 1


def test_transient_official_fetch_error_keeps_route_retryable(
    session_factory,
) -> None:
    class FailingFaqFetcher(PageFetcher):
        def get(self, url: str) -> FetchResponse:
            if url.endswith("/faq"):
                raise TimeoutError("temporary FAQ timeout")
            return super().get(url)

    with session_factory.begin() as session:
        collection = _collect_article(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        first = prepare_statusmatch_article_projects(session, FailingFaqFetcher())
        route = session.scalar(select(StatusMatchArticleRoute))
        watch = session.scalar(select(StatusMatchWatch))
        assert route is not None and route.status == "WAITING_OFFICIAL"
        assert watch is not None and watch.last_error is not None

    assert first.monitoring.errors
    with session_factory.begin() as session:
        second = prepare_statusmatch_article_projects(session, PageFetcher())
        route = session.scalar(select(StatusMatchArticleRoute))
        watch = session.scalar(select(StatusMatchWatch))
        assert route is not None and route.status == "WAITING_OFFICIAL"
        assert watch is not None and watch.status == "ACTIVE"
        assert watch.last_error is None
    assert second.monitoring.errors == ()
    assert len(second.hosts_fetched) == 1


def test_historical_route_is_not_moved_to_a_later_watch_generation(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        old_watch, old_event, _, _ = _seed_official_output(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
        route = session.scalar(select(StatusMatchArticleRoute))
        assert route is not None and route.event_id == old_event.id
        old_event_id = old_event.id
        old_event.archived_at = datetime.now(UTC)
        delete_watch_only(session, old_watch)
        _new_watch, new_event, _, _ = _seed_official_output(session)
        refresh_statusmatch_article_route_readiness(session)
        session.refresh(route)

    assert route.event_id == old_event_id
    assert route.event_id != new_event.id


def test_highlight_processing_retries_duplicates_and_is_idempotent(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        _seed_official_output(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
    provider = SequenceAIProvider(
        [
            {
                "schema_version": "3",
                "highlights": ["重复关注点。", "重复关注点。"],
            },
            _highlight_response(),
        ]
    )

    first = process_pending_statusmatch_articles(session_factory, provider)
    second = process_pending_statusmatch_articles(session_factory, provider)

    assert first.succeeded == 1 and first.model_calls == 2
    assert first.routes[0].highlight_count == 1
    assert first.routes[0].article_title == "Kenya Airways match"
    assert first.routes[0].article_url == ARTICLE_URL
    assert second.selected == 0 and second.model_calls == 0
    assert len(provider.calls) == 2
    assert "correction" in provider.calls[1]["user_prompt"]
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(StatusMatchArticleSupplement)
        ) == 1
        assert set(session.scalars(select(AnalysisRun.stage))) == {
            "STATUSMATCH_ARTICLE_HIGHLIGHTS"
        }


def test_zero_highlight_is_successful_and_composed_without_polluting_official(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        _, event, fact, brief = _seed_official_output(session)
        original_fact = dict(fact.facts)
        original_brief = dict(brief.content)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
        event_id = event.id
        fact_id = fact.id
        brief_id = brief.id
    provider = SequenceAIProvider(
        [{"schema_version": "1", "highlights": []}]
    )

    result = process_pending_statusmatch_articles(session_factory, provider)

    assert result.routes[0].status == "NO_NOVEL_HIGHLIGHTS"
    with session_factory() as session:
        composed = composed_statusmatch_brief(session, event_id=event_id)
        fact = session.get(FactSetRecord, fact_id)
        brief = session.get(BriefRecord, brief_id)
        assert fact is not None and fact.facts == original_fact
        assert brief is not None and brief.content == original_brief
        assert composed.supplements == []


def test_composed_brief_is_exposed_by_review_api_and_cli_parser(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        _seed_official_output(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
    process_pending_statusmatch_articles(
        session_factory, SequenceAIProvider([_highlight_response()])
    )

    response = TestClient(create_review_app(session_factory)).get(
        f"/internal/statusmatch/projects/{HOST}/brief"
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "title",
        "summary",
        "key_points",
        "caveats",
        "source_links",
        "supplements",
    }
    assert payload["title"] == "Kenya Airways 开放会籍匹配"
    assert payload["key_points"] == ["符合条件的 Accor 会员可以申请。"]
    supplement = payload["supplements"][0]
    assert set(supplement) == {
        "article_title",
        "article_url",
        "article_published_at",
        "highlights",
    }
    assert supplement["highlights"] == ["文章额外提醒了一项实际注意事项。"]
    with session_factory() as session:
        stored = session.scalar(select(BriefRecord))
        assert stored is not None
        assert stored.content["fact_set_id"]
        assert stored.content["title_fact_keys"] == ["what_happened"]
        assert stored.content["key_points"][0]["fact_keys"] == ["what_happened"]
    assert build_parser().parse_args(
        ["statusmatch-articles", "--source-id", "loyaltylobby_feed"]
    ).command == "statusmatch-articles"
    assert build_parser().parse_args(
        ["statusmatch-brief", HOST]
    ).command == "statusmatch-brief"


def test_daily_cycle_runs_article_branch_before_generic_workflow(
    session_factory,
) -> None:
    provider = DailyArticleProvider()
    fetcher = PageFetcher()

    result = run_daily_cycle(
        session_factory,
        provider,
        lambda _source_id: ArticleAdapter(),
        source_ids=["loyaltylobby_feed"],
        statusmatch_fetcher=fetcher,
        now=datetime(2026, 8, 25, 1, tzinfo=UTC),
    )

    assert result.status == "SUCCEEDED"
    assert result.statusmatch_article_routes_created == 1
    assert result.statusmatch_article_hosts_fetched == (HOST,)
    assert result.statusmatch_projects_succeeded == 1
    assert result.statusmatch_articles_succeeded == 1
    assert result.statusmatch_article_model_calls == 1
    assert result.statusmatch_article_outputs[0]["article_title"] == (
        "Kenya Airways match"
    )
    assert result.statusmatch_article_outputs[0]["article_url"] == ARTICLE_URL
    assert result.documents_selected == 0
    assert provider.calls == [
        "StatusMatchProjectExtraction",
        "Brief",
        "StatusMatchArticleExtraction",
    ]
    with session_factory() as session:
        article_document_id = session.scalar(
            select(StatusMatchArticleRoute.document_version_id)
        )
        assert session.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(
                AnalysisRun.document_version_id == article_document_id,
                AnalysisRun.stage.in_(
                    (
                        "STATUS_RELEVANCE",
                        "EVENT_RELATIONSHIP",
                        "FACT_CONSOLIDATION",
                        "BRIEF_GENERATION",
                    )
                ),
            )
        ) == 0

    status = automation_status(session_factory, provider)
    assert status.last_statusmatch_articles_succeeded == 1
    assert status.last_statusmatch_article_outputs[0]["article_url"] == ARTICLE_URL


def test_official_version_change_creates_new_current_supplement(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect_article(session)
        _, event, _, _ = _seed_official_output(session)
        discover_statusmatch_article_routes(
            session, document_ids=collection.current_document_version_ids
        )
        refresh_statusmatch_article_route_readiness(session)
        event_id = event.id
    first = SequenceAIProvider([_highlight_response()])
    assert process_pending_statusmatch_articles(session_factory, first).succeeded == 1

    with session_factory.begin() as session:
        event = session.get(StatusEvent, event_id)
        assert event is not None
        fact = FactSetRecord(
            event_id=event.id,
            version=2,
            schema_version="4",
            facts={"what_happened": {"value": "Updated official facts"}},
        )
        session.add(fact)
        session.flush()
        brief = BriefRecord(
            fact_set_id=fact.id,
            version=1,
            schema_version="1",
            content={
                "schema_version": "1",
                "fact_set_id": str(fact.id),
                "title": "Updated official brief",
                "title_fact_keys": ["what_happened"],
                "summary": "Updated official summary",
                "summary_fact_keys": ["what_happened"],
                "key_points": [],
                "caveats": [],
                "source_links": [],
            },
        )
        session.add(brief)
        session.flush()
        event.current_fact_set_id = fact.id
        event.current_brief_id = brief.id
    second = SequenceAIProvider(
        [{"schema_version": "1", "highlights": []}]
    )

    result = process_pending_statusmatch_articles(session_factory, second)

    assert result.succeeded == 1
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(StatusMatchArticleSupplement)
        ) == 2
        composed = composed_statusmatch_brief(session, event_id=event_id)
        assert composed.supplements == []
