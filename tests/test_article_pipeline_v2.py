from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.article_operations import (
    pending_article_documents,
    process_pending_articles,
)
from journeyplus.article_pipeline.evaluation import (
    TitleScreenGoldCase,
    run_title_screen_shadow,
)
from journeyplus.article_pipeline.read_model import (
    article_analysis_history,
    latest_successful_article_view,
)
from journeyplus.article_pipeline.screening import BatchTitleScreener
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import (
    AnalysisRun,
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    SourceItem,
)
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources


class ArticleBatchAdapter:
    source_id = "loyaltylobby_feed"

    def __init__(self, articles: list[tuple[str, str, str]]) -> None:
        self.articles = articles

    def discover(self):
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=external_id,
                discovered_url=f"https://loyaltylobby.com/{external_id}/",
                canonical_url=f"https://loyaltylobby.com/{external_id}/",
                title=title,
                raw_metadata={"refresh_on_discovery": True},
            )
            for external_id, title, _body in self.articles
        ]

    def fetch(self, item):
        body = next(
            body for external_id, _title, body in self.articles
            if external_id == item.external_id
        )
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=body,
            content_type="text/plain",
        )


class V2Provider:
    metadata = AIProviderMetadata(
        provider="test",
        model="article-v2",
        region="local",
        config_version="article-v2-test",
    )

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_structured(self, *, system_prompt, user_prompt, output_model):
        request = json.loads(user_prompt)
        self.calls.append(
            {"model": output_model.__name__, "request": request, "prompt": system_prompt}
        )
        if output_model.__name__ == "TitleScreenBatch":
            return output_model.model_validate(
                {
                    "items": [
                        {
                            "document_version_id": item["document_version_id"],
                            "decision": (
                                "DROP" if "points sale" in item["title"].casefold()
                                else "PASS"
                            ),
                            "confidence": 0.99,
                            "reason": "标题明确",
                        }
                        for item in request["items"]
                    ]
                }
            )
        if output_model.__name__ == "ArticleInterpretation":
            body = request["normalized_body"]
            if "ordinary lounge news" in body:
                return output_model.model_validate(
                    {
                        "label": "NONE",
                        "confidence": 0.99,
                        "reason": "正文没有会籍机会",
                    }
                )
            quote = "Example Air offers a direct status match to Gold."
            action_link = "https://example-air.test/apply"
            return output_model.model_validate(
                {
                    "label": "STATUS_OPPORTUNITY",
                    "confidence": 0.99,
                    "reason": "正文明确报道直接会籍匹配",
                    "opportunities": [
                        {
                            "opportunity_index": 0,
                            "program": "Example Air",
                            "target_status_name": "Gold",
                            "summary": "Example Air 开放 Gold 会籍匹配",
                            "what_happened": {
                                "value": "Example Air offers a direct status match to Gold.",
                                "evidence": [{"quote": quote}],
                            },
                            "target_status": {
                                "value": "Gold",
                                "evidence": [{"quote": quote}],
                            },
                            "action_link": {
                                "value": action_link,
                                "evidence": [{"quote": action_link}],
                            },
                        }
                    ],
                }
            )
        if output_model.__name__ == "Brief":
            return output_model.model_validate(
                {
                    "fact_set_id": request["fact_set_id"],
                    "title": "Example Air 开放 Gold 会籍匹配",
                    "title_fact_keys": ["what_happened", "target_status"],
                    "summary": "Example Air 正在提供直达 Gold 的会籍匹配。",
                    "summary_fact_keys": ["what_happened", "target_status"],
                    "key_points": [],
                    "caveats": [],
                    "source_links": request["allowed_source_links"],
                }
            )
        raise AssertionError(output_model.__name__)


def _collect(session, articles):
    seed_sources(session)
    return collect_manual(session, ArticleBatchAdapter(articles))


def test_v2_batches_titles_omits_bodies_and_reuses_every_stage(session_factory) -> None:
    secret = "FULL_BODY_SENTINEL_MUST_NOT_REACH_TITLE_SCREEN"
    with session_factory.begin() as session:
        _collect(
            session,
            [
                ("sale", "Hotel points sale", secret),
                (
                    "match",
                    "Example Air launches a status match",
                    "Example Air offers a direct status match to Gold. "
                    "Apply at https://example-air.test/apply",
                ),
            ],
        )
    provider = V2Provider()

    first = process_pending_articles(session_factory, provider, limit=10)
    second = process_pending_articles(session_factory, provider, limit=10)

    assert (first.selected, first.title_dropped, first.body_processed) == (2, 1, 1)
    assert (first.opportunities, first.briefs) == (1, 1)
    assert (
        first.title_model_calls,
        first.interpretation_model_calls,
        first.brief_model_calls,
    ) == (1, 1, 1)
    assert first.model_calls == 3
    assert second.selected == second.model_calls == 0
    title_call = provider.calls[0]
    assert title_call["model"] == "TitleScreenBatch"
    assert secret not in json.dumps(title_call["request"])
    assert set(title_call["request"]) == {"items"}
    assert all(set(item) == {"document_version_id", "title"} for item in title_call["request"]["items"])
    with session_factory() as session:
        match_item = session.scalar(
            select(SourceItem).where(SourceItem.external_id == "match")
        )
        assert match_item is not None
        view = latest_successful_article_view(session, match_item.id)
        assert view is not None and len(view.opportunities) == 1
        assert view.opportunities[0].brief is not None
        assert session.scalar(select(func.count()).select_from(ArticleBriefRecord)) == 1


def test_title_failure_falls_through_to_body_and_shadow_detects_positive_drop(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect(
            session,
            [("unclear", "A surprising airline change", "ordinary lounge news")],
        )
    provider = SequenceAIProvider(
        [
            RuntimeError("title service unavailable"),
            {
                "label": "NONE",
                "confidence": 0.99,
                "reason": "正文无会籍机会",
                "opportunities": [],
            },
        ]
    )

    result = process_pending_articles(session_factory, provider)

    assert result.succeeded == result.body_processed == 1
    assert result.documents[0].title_decision == "NEEDS_BODY"
    assert result.title_model_calls == result.interpretation_model_calls == 1
    with session_factory() as session:
        title_run = session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.stage == "ARTICLE_TITLE_SCREENING"
            )
        )
        assert title_run is not None and title_run.status == "FAILED"
        assert pending_article_documents(session, provider) == []

    with session_factory.begin() as session:
        shadow_collection = _collect(
            session,
            [("shadow-positive", "Hidden status opportunity", "positive body")],
        )
        shadow_document_id = UUID(shadow_collection.current_document_version_ids[0])
        shadow = run_title_screen_shadow(
            session,
            SequenceAIProvider(
                [
                    {
                        "items": [
                            {
                                "document_version_id": str(shadow_document_id),
                                "decision": "DROP",
                                "confidence": 0.99,
                                "reason": "误判样例",
                            }
                        ]
                    }
                ]
            ),
            [TitleScreenGoldCase(shadow_document_id, expected_positive=True)],
        )
    assert shadow.positive_drops == 1 and not shadow.safe_to_enable_drop


def test_disabling_title_drop_reprocesses_prior_drop_without_recalling_title(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _collect(
            session,
            [("drop-policy", "Hotel points sale", "ordinary lounge news")],
        )
    provider = V2Provider()

    dropped = process_pending_articles(session_factory, provider)
    inspected = process_pending_articles(
        session_factory, provider, title_drop_enabled=False
    )
    repeated = process_pending_articles(
        session_factory, provider, title_drop_enabled=False
    )

    assert dropped.title_dropped == 1 and dropped.model_calls == 1
    assert inspected.selected == inspected.body_processed == 1
    assert inspected.documents[0].document_label == "NONE"
    assert inspected.title_model_calls == 0
    assert inspected.interpretation_model_calls == inspected.model_calls == 1
    assert repeated.selected == repeated.model_calls == 0


def test_identical_articles_remain_independent_without_relationship_stages(
    session_factory,
) -> None:
    body = (
        "Example Air offers a direct status match to Gold. "
        "Apply at https://example-air.test/apply"
    )
    with session_factory.begin() as session:
        _collect(
            session,
            [
                ("copy-a", "Example Air status match A", body),
                ("copy-b", "Example Air status match B", body),
            ],
        )
    provider = V2Provider()

    result = process_pending_articles(session_factory, provider)

    assert result.opportunities == 2
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ArticleAnalysisRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ArticleOpportunityRecord)) == 2
        stages = set(session.scalars(select(AnalysisRun.stage)))
        assert "EVENT_RELATIONSHIP" not in stages
        assert "FACT_CONSOLIDATION" not in stages


def test_exact_statusmatch_link_is_excluded_before_title_screen(session_factory) -> None:
    with session_factory.begin() as session:
        _collect(
            session,
            [
                (
                    "linked",
                    "Kenya Airways status match",
                    '<a href="https://kenya-airways.statusmatch.com/">apply</a>',
                )
            ],
        )
    provider = SequenceAIProvider([])

    result = process_pending_articles(session_factory, provider)

    assert result.selected == 0
    assert provider.calls == []


def test_brief_failure_keeps_analysis_and_retries_only_the_brief(session_factory) -> None:
    body = (
        "Example Air offers a direct status match to Gold. "
        "Apply at https://example-air.test/apply"
    )
    with session_factory.begin() as session:
        _collect(session, [("brief-retry", "Example Air status match", body)])

    class BriefRetryProvider(V2Provider):
        fail_brief = True

        def generate_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model.__name__ == "Brief" and self.fail_brief:
                self.calls.append({"model": "Brief", "request": {}})
                raise ValueError("simulated ungrounded brief")
            return super().generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
            )

    provider = BriefRetryProvider()
    failed = process_pending_articles(session_factory, provider)

    assert failed.failed == 1 and failed.brief_model_calls == 2
    assert failed.body_processed == failed.status_opportunities == 1
    assert failed.opportunities == 1 and failed.briefs == 0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ArticleAnalysisRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArticleOpportunityRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArticleBriefRecord)) == 0

    provider.fail_brief = False
    recovered = process_pending_articles(session_factory, provider)

    assert recovered.succeeded == recovered.briefs == 1
    assert recovered.title_model_calls == recovered.interpretation_model_calls == 0
    assert recovered.brief_model_calls == 1
    with session_factory() as session:
        opportunity = session.scalar(select(ArticleOpportunityRecord))
        assert opportunity is not None and opportunity.status == "DRAFT"


def test_article_pipeline_has_no_statusmatch_or_legacy_relationship_dependency() -> None:
    package = Path(__file__).parents[1] / "src/journeyplus/article_pipeline"
    forbidden_symbols = {
        "CandidateRetriever",
        "EventRelationshipAnalyzer",
        "EventAggregator",
        "FactConsolidator",
    }
    seen_names: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("journeyplus.statusmatch")
                    for alias in node.names
                )
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("journeyplus.statusmatch")
            if isinstance(node, ast.Name):
                seen_names.add(node.id)
    assert forbidden_symbols.isdisjoint(seen_names)


def test_title_screening_is_batched_and_one_bad_chunk_falls_through(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        collection = _collect(
            session,
            [
                ("batch-a", "Possible status offer A", "BODY_A"),
                ("batch-b", "Possible status offer B", "BODY_B"),
                ("batch-c", "Clear status match C", "BODY_C"),
            ],
        )
        documents = [
            session.get(DocumentVersion, UUID(value))
            for value in collection.current_document_version_ids
        ]
        assert all(document is not None for document in documents)
        last_id = documents[-1].id
        provider = SequenceAIProvider(
            [
                {
                    "items": [
                        {
                            "document_version_id": str(documents[0].id),
                            "decision": "PASS",
                            "confidence": 0.99,
                            "reason": "故意遗漏同批另一项",
                        }
                    ]
                },
                {
                    "items": [
                        {
                            "document_version_id": str(last_id),
                            "decision": "PASS",
                            "confidence": 0.99,
                            "reason": "明确命中",
                        }
                    ]
                },
            ]
        )

        outcomes = BatchTitleScreener(
            session, provider, batch_size=2
        ).screen(documents)

    assert len(provider.calls) == 2
    assert [item.result.decision for item in outcomes] == [
        "NEEDS_BODY",
        "NEEDS_BODY",
        "PASS",
    ]
    serialized_requests = json.dumps(provider.calls)
    assert all(marker not in serialized_requests for marker in ("BODY_A", "BODY_B", "BODY_C"))


def test_multi_opportunity_article_uses_one_body_call_and_one_brief_per_opportunity(
    session_factory,
) -> None:
    alpha_quote = "Alpha Air offers a direct status match to Gold."
    beta_quote = "Beta Hotel offers a direct status match to Platinum."
    body = (
        f"{alpha_quote} Apply at https://alpha.test/apply. "
        f"{beta_quote} Apply at https://beta.test/apply."
    )
    with session_factory.begin() as session:
        _collect(session, [("multi", "Two independent status matches", body)])

    class MultiOpportunityProvider(V2Provider):
        def generate_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model.__name__ != "ArticleInterpretation":
                return super().generate_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    output_model=output_model,
                )
            request = json.loads(user_prompt)
            self.calls.append(
                {"model": output_model.__name__, "request": request, "prompt": system_prompt}
            )
            return output_model.model_validate(
                {
                    "label": "STATUS_OPPORTUNITY",
                    "confidence": 0.99,
                    "reason": "正文包含两个独立目标项目和入口",
                    "opportunities": [
                        {
                            "opportunity_index": 0,
                            "program": "Alpha Air",
                            "target_status_name": "Gold",
                            "summary": "Alpha Air Gold 会籍匹配",
                            "what_happened": {
                                "value": alpha_quote,
                                "evidence": [{"quote": alpha_quote}],
                            },
                            "target_status": {
                                "value": "Gold",
                                "evidence": [{"quote": alpha_quote}],
                            },
                            "action_link": {
                                "value": "https://alpha.test/apply",
                                "evidence": [{"quote": "https://alpha.test/apply"}],
                            },
                        },
                        {
                            "opportunity_index": 1,
                            "program": "Beta Hotel",
                            "target_status_name": "Platinum",
                            "summary": "Beta Hotel Platinum 会籍匹配",
                            "what_happened": {
                                "value": beta_quote,
                                "evidence": [{"quote": beta_quote}],
                            },
                            "target_status": {
                                "value": "Platinum",
                                "evidence": [{"quote": beta_quote}],
                            },
                            "action_link": {
                                "value": "https://beta.test/apply",
                                "evidence": [{"quote": "https://beta.test/apply"}],
                            },
                        },
                    ],
                }
            )

    provider = MultiOpportunityProvider()
    first = process_pending_articles(session_factory, provider)
    second = process_pending_articles(session_factory, provider)

    assert (first.title_model_calls, first.interpretation_model_calls) == (1, 1)
    assert first.brief_model_calls == first.briefs == first.opportunities == 2
    assert first.model_calls == 4
    assert second.selected == second.model_calls == 0
    with session_factory() as session:
        opportunities = list(
            session.scalars(
                select(ArticleOpportunityRecord).order_by(
                    ArticleOpportunityRecord.opportunity_index
                )
            )
        )
        assert [item.program for item in opportunities] == [
            "Alpha Air",
            "Beta Hotel",
        ]
        assert opportunities[0].action_links != opportunities[1].action_links


def test_new_document_version_preserves_history_and_becomes_latest_view(
    session_factory,
) -> None:
    first_body = (
        "Example Air offers a direct status match to Gold. "
        "Apply at https://example-air.test/apply"
    )
    adapter = ArticleBatchAdapter(
        [("versioned", "Example Air launches a status match", first_body)]
    )
    with session_factory.begin() as session:
        seed_sources(session)
        first_collection = collect_manual(session, adapter)
    provider = V2Provider()
    first = process_pending_articles(session_factory, provider)
    assert first.opportunities == 1

    adapter.articles = [
        (
            "versioned",
            "Example Air launches a status match",
            first_body + " Updated terms are now available.",
        )
    ]
    with session_factory.begin() as session:
        second_collection = collect_manual(session, adapter)
    second = process_pending_articles(session_factory, provider)

    assert second_collection.new_versions == 1
    assert first_collection.current_document_version_ids != second_collection.current_document_version_ids
    assert second.opportunities == 1
    with session_factory() as session:
        item = session.scalar(
            select(SourceItem).where(SourceItem.external_id == "versioned")
        )
        assert item is not None
        history = article_analysis_history(session, item.id)
        latest = latest_successful_article_view(session, item.id)
        assert len(history) == 2
        assert len({record.document_version_id for record in history}) == 2
        assert latest is not None
        assert str(latest.document_version_id) == second_collection.current_document_version_ids[0]
        assert session.scalar(select(func.count()).select_from(ArticleOpportunityRecord)) == 2
