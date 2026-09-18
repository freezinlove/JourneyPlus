from hashlib import sha256
import json

import pytest
from sqlalchemy import event, func, select

from journeyplus.article_operations import process_pending_articles
from journeyplus.sources.article_admission import AdmissionRetryRequired
from journeyplus.models import (AnalysisRun, ArticleAnalysisRecord, ArticleOpportunityRecord,
                                ArticleBriefRecord, CollectionRun, DocumentVersion, JobRun,
                                SourceAutomationState, SourceItem)
from journeyplus.sources.collection import collect_in_phases
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.articles import discover_statusmatch_article_routes
from tests.test_article_pipeline_v2 import ArticleBatchAdapter, V2Provider

BODY = 'Example Air offers a direct status match to Gold. Apply at https://example-air.test/apply'


class Feed(ArticleBatchAdapter):
    def __init__(self, articles):
        super().__init__(articles)
        self.cursor = None
        self.fetched = []

    def configure_feed_incremental_discovery(self, *, discovery_cursor):
        self.cursor = discovery_cursor

    def discover(self):
        items = super().discover()
        for item, (_, _, body) in zip(items, self.articles):
            item.discovery_fingerprint = sha256(body.encode()).hexdigest()
            item.raw_metadata = {'feed_body': body}
        if self.cursor:
            items = items[[i.external_id for i in items].index(self.cursor) + 1:]
        return items

    def fetch(self, item):
        self.fetched.append(item.external_id)
        return super().fetch(item)

    def discovery_cursor_after_collection(self, *, considered_items, fully_considered):
        return considered_items[-1].external_id if considered_items else self.cursor


def collect(factory, feed, provider, key='admission', **kwargs):
    with factory.begin() as s:
        seed_sources(s)
    return collect_in_phases(factory, feed, idempotency_key=key,
                             article_provider=provider, **kwargs)


def test_only_final_positive_enters_database_and_model_work_is_reused(session_factory):
    feed = Feed([('drop', 'Points sale', 'PRIVATE DROP BODY'),
                 ('none', 'Airline news', 'ordinary lounge news PRIVATE NONE BODY'),
                 ('yes', 'Status match offer', BODY)])
    provider = V2Provider()
    result = collect(session_factory, feed, provider)
    assert (result.considered, result.new_versions, result.title_dropped, result.body_dropped) == (3, 1, 1, 1)
    assert feed.fetched == ['none', 'yes']
    assert (result.title_model_calls, result.interpretation_model_calls) == (1, 2)
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(SourceItem)) == 1
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert s.scalar(select(func.count()).select_from(ArticleAnalysisRecord)) == 1
        assert s.scalar(select(func.count()).select_from(ArticleOpportunityRecord)) == 1
        assert s.scalar(select(SourceItem)).external_id == 'yes'
        assert s.get(SourceAutomationState, feed.source_id).discovery_cursor == 'yes'
        assert len(list(s.scalars(select(JobRun)))) == 2
        assert 'PRIVATE' not in json.dumps([r.result for r in s.scalars(select(JobRun))])
        assert 'PRIVATE' not in json.dumps([r.result for r in s.scalars(select(AnalysisRun))])
    produced = process_pending_articles(session_factory, provider)
    assert produced.succeeded == 1 and produced.briefs == 1
    assert (produced.title_model_calls, produced.interpretation_model_calls, produced.brief_model_calls) == (0, 0, 0)
    call_count = len(provider.calls)
    repeated = collect(session_factory, feed, provider, 'next')
    assert repeated.considered == 0 and len(provider.calls) == call_count
    title_request = provider.calls[0]['request']
    assert all(set(item) == {'document_version_id', 'title'} for item in title_request['items'])


def test_failure_preserves_completed_prefix_and_retries_uncertain_item(session_factory):
    feed = Feed([('drop', 'Points sale', 'never fetch'), ('retry', 'Status match offer', BODY),
                 ('later', 'Later offer', BODY)])
    class Uncertain(V2Provider):
        def generate_structured(self, **kwargs):
            if kwargs['output_model'].__name__ == 'ArticleInterpretation':
                return kwargs['output_model'].model_validate({'label':'UNCERTAIN','confidence':0.3,'reason':'uncertain'})
            return super().generate_structured(**kwargs)
    with pytest.raises(AdmissionRetryRequired):
        collect(session_factory, feed, Uncertain())
    with session_factory() as s:
        assert s.get(SourceAutomationState, feed.source_id).discovery_cursor == 'drop'
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert s.scalar(select(CollectionRun)).status == 'FAILED'
    assert feed.fetched == ['retry']
    retried = collect(session_factory, feed, V2Provider())
    assert retried.new_versions == 2 and retried.considered == 2
    assert feed.fetched == ['retry', 'retry', 'later']


def test_partial_limit_and_negative_only_batch_advance_cursor(session_factory):
    feed = Feed([('a', 'Points sale', 'a'), ('b', 'Points sale', 'b')])
    provider = V2Provider()
    first = collect(session_factory, feed, provider, max_items=1)
    assert first.title_dropped == 1 and first.new_versions == 0
    with session_factory() as s:
        assert s.get(SourceAutomationState, feed.source_id).discovery_cursor == 'a'
    second = collect(session_factory, feed, provider, 'second')
    assert second.considered == 1 and second.new_versions == 0
    assert not feed.fetched
    # Lost/reset cursor still skips terminal negatives using content fingerprints.
    with session_factory.begin() as s:
        s.get(SourceAutomationState, feed.source_id).discovery_cursor = None
    calls = len(provider.calls)
    collect(session_factory, feed, provider, 'third')
    assert len(provider.calls) == calls


def test_linked_article_directly_routes_without_title_or_body_models(session_factory):
    feed = Feed([('linked', 'Points sale', BODY + ' See https://example.statusmatch.com/')])
    provider = V2Provider()
    result = collect(session_factory, feed, provider)
    assert result.new_versions == 1
    assert provider.calls == []
    assert result.title_model_calls == result.interpretation_model_calls == 0
    with session_factory.begin() as s:
        assert s.scalar(select(func.count()).select_from(ArticleOpportunityRecord)) == 0
        assert s.scalar(select(ArticleAnalysisRecord)) is None
        assert s.scalar(select(AnalysisRun)) is None
        routes = discover_statusmatch_article_routes(s)
        assert routes.routes_created == 1
        assert routes.project_hosts == ('example.statusmatch.com',)


def test_model_and_http_run_before_storage_without_open_connections(session_factory):
    engine = session_factory.kw['bind']
    active = []
    def checkout(*args): active.append(1)
    def checkin(*args): active.pop()
    with session_factory.begin() as s: seed_sources(s)
    event.listen(engine, 'checkout', checkout)
    event.listen(engine, 'checkin', checkin)
    class CheckedProvider(V2Provider):
        def generate_structured(self, **kwargs):
            assert not active
            with session_factory() as s:
                assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0
            return super().generate_structured(**kwargs)
    class CheckedFeed(Feed):
        def fetch(self, item):
            assert not active
            return super().fetch(item)
    try:
        collect(session_factory, CheckedFeed([('yes', 'Status match', BODY)]), CheckedProvider())
    finally:
        event.remove(engine, 'checkout', checkout)
        event.remove(engine, 'checkin', checkin)


def test_public_collection_cannot_bypass_admission(session_factory):
    with pytest.raises(ValueError, match='admission'):
        collect_in_phases(session_factory, Feed([]), idempotency_key='no-provider')


def test_daily_cycle_includes_admission_calls_and_finishes_brief(session_factory):
    from journeyplus.automation.service import run_daily_cycle
    feed = Feed([('drop', 'Points sale', 'private'), ('none', 'Airline news', 'ordinary lounge news'),
                 ('yes', 'Status match', BODY)])
    provider = V2Provider()
    result = run_daily_cycle(session_factory, provider, lambda sid: feed,
                             source_ids=['loyaltylobby_feed'])
    assert result.status == 'SUCCEEDED'
    assert result.model_calls == 3
    assert (result.generic_title_model_calls, result.generic_interpretation_model_calls,
            result.generic_brief_model_calls) == (1, 2, 0)
    assert result.sources[0].title_dropped == result.sources[0].body_dropped == 1
    assert result.backlog_count == 0
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ArticleBriefRecord)) == 1


def test_failed_publication_rolls_back_body_and_cursor(session_factory, monkeypatch):
    from journeyplus.article_pipeline.interpretation import ArticleInterpreter
    def reject(*args, **kwargs):
        raise ValueError('publication failed')
    monkeypatch.setattr(ArticleInterpreter, '_materialize', reject)
    feed = Feed([('yes', 'Status match', BODY)])
    with pytest.raises(ValueError, match='publication failed'):
        collect(session_factory, feed, V2Provider())
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(SourceItem)) == 0
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert s.get(SourceAutomationState, feed.source_id).discovery_cursor is None


def test_changed_cursor_rejects_stale_publication(session_factory):
    class RacingProvider(V2Provider):
        def generate_structured(self, **kwargs):
            value = super().generate_structured(**kwargs)
            if kwargs['output_model'].__name__ == 'ArticleInterpretation':
                with session_factory.begin() as s:
                    s.get(SourceAutomationState, 'loyaltylobby_feed').discovery_cursor = 'other-worker'
            return value
    with pytest.raises(AdmissionRetryRequired, match='cursor changed'):
        collect(session_factory, Feed([('yes', 'Status match', BODY)]), RacingProvider())
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert s.get(SourceAutomationState, 'loyaltylobby_feed').discovery_cursor == 'other-worker'


def test_model_budget_failure_keeps_cursor_and_reports_actual_calls(session_factory):
    from journeyplus.automation.service import run_daily_cycle, AutomationLimits
    feed = Feed([('yes', 'Status match', BODY)])
    result = run_daily_cycle(session_factory, V2Provider(), lambda sid: feed,
                             source_ids=['loyaltylobby_feed'], limits=AutomationLimits(model_calls=1))
    assert result.status == 'FAILED' and result.model_calls == 1
    assert result.generic_title_model_calls == 1
    assert result.generic_interpretation_model_calls == 0
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert s.get(SourceAutomationState, feed.source_id).discovery_cursor is None


def test_exact_project_link_overrides_old_rejection_marker(session_factory):
    from journeyplus.sources.article_admission import remember_rejection
    feed = Feed([('linked', 'Points sale', BODY + ' https://example.statusmatch.com/')])
    with session_factory.begin() as s:
        seed_sources(s)
        remember_rejection(s, feed.discover()[0], 'TITLE_DROP')
    provider = V2Provider()
    result = collect(session_factory, feed, provider)
    assert result.new_versions == 1 and provider.calls == []
    with session_factory() as s:
        assert s.scalar(select(JobRun).where(JobRun.job_type == 'article_admission')) is None


@pytest.mark.parametrize('link', ['https://statusmatch.com/', 'https://www.statusmatch.com/',
                                  'https://example.statusmatch.com.evil.test/', 'statusmatch'])
def test_only_exact_official_project_links_bypass_screening(session_factory, link):
    provider = V2Provider()
    result = collect(session_factory, Feed([('ordinary', 'Points sale', BODY + ' ' + link)]), provider)
    assert result.title_dropped == 1 and result.new_versions == 0
    assert [c['model'] for c in provider.calls] == ['TitleScreenBatch']
