from sqlalchemy import event, select
from tests.db_fixture import factory
from tests.test_statusmatch_monitoring import PageFetcher, _active_responses
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch
from journeyplus.statusmatch.monitoring import monitor_statusmatch_projects
from journeyplus.models import StatusMatchWatch


def test_official_http_has_no_checked_out_database_connection(factory):
    with factory.begin() as s:
        seed_sources(s)
        ensure_statusmatch_watch(s, 'test.statusmatch.com')
    engine=factory.kw['bind'];checked_out=[]
    def checkout(*args):checked_out.append(1)
    def checkin(*args):checked_out.pop()
    event.listen(engine,'checkout',checkout);event.listen(engine,'checkin',checkin)
    try:
        responses={url.replace('example.statusmatch.com','test.statusmatch.com'):body for url,body in _active_responses().items()}
        class CheckedFetcher(PageFetcher):
            def get(self,url):
                assert not checked_out
                return super().get(url)
        # Use URLs from the persisted watch to avoid coupling to fixture host names.
        from tests.test_statusmatch_monitoring import ACTIVE_ACTIVITY,ACTIVE_FAQ,ACTIVE_TERMS
        responses={'https://test.statusmatch.com/':ACTIVE_ACTIVITY,'https://test.statusmatch.com/faq':ACTIVE_FAQ,'https://test.statusmatch.com/terms':ACTIVE_TERMS}
        fetcher=CheckedFetcher(responses)
        result=monitor_statusmatch_projects(factory,fetcher)
        assert not result.errors and result.pages_checked==3
        repeated=monitor_statusmatch_projects(factory,fetcher)
        assert repeated.pages_changed==0
    finally:
        event.remove(engine,'checkout',checkout);event.remove(engine,'checkin',checkin)


def test_project_model_runs_without_database_connections(factory):
    from tests.test_statusmatch_project_workflow import _seed_active_watch, ProjectProvider, _extraction
    from journeyplus.statusmatch.project_workflow import process_pending_statusmatch_projects
    with factory.begin() as s:_seed_active_watch(s)
    engine=factory.kw['bind'];active=[]
    def checkout(*args):active.append(1)
    def checkin(*args):active.pop()
    event.listen(engine,'checkout',checkout);event.listen(engine,'checkin',checkin)
    try:
        class CheckedProvider(ProjectProvider):
            def generate_structured(self,**kwargs):
                assert not active, 'Model called with a database connection checked out'
                return super().generate_structured(**kwargs)
        result=process_pending_statusmatch_projects(factory,CheckedProvider([_extraction()]))
        assert result.succeeded==1 and result.failed==0 and result.model_calls==1
    finally:
        event.remove(engine,'checkout',checkout);event.remove(engine,'checkin',checkin)


def test_source_change_during_model_cannot_publish_stale_facts(factory):
    from tests.test_statusmatch_project_workflow import _seed_active_watch, ProjectProvider, _extraction
    from journeyplus.statusmatch.project_workflow import process_pending_statusmatch_projects
    from journeyplus.models import StatusMatchWatchPage,FactSetRecord
    with factory.begin() as s:_seed_active_watch(s)
    class RacingProvider(ProjectProvider):
        def generate_structured(self,**kwargs):
            result=super().generate_structured(**kwargs)
            if kwargs['output_model'].__name__=='StatusMatchProjectExtraction':
                with factory.begin() as s:
                    page=s.scalar(select(StatusMatchWatchPage).where(StatusMatchWatchPage.page_kind=='faq'))
                    page.last_error='Concurrent source refresh failed'
            return result
    result=process_pending_statusmatch_projects(factory,RacingProvider([_extraction()]))
    assert result.failed==1 and result.succeeded==0
    with factory() as s:assert s.scalar(select(FactSetRecord)) is None


def test_source_discovery_and_fetch_are_outside_transactions(factory):
    from journeyplus.sources.collection import collect_in_phases
    from tests.test_automation import SyntheticAdapter
    with factory.begin() as s:seed_sources(s)
    engine=factory.kw['bind'];active=[]
    def checkout(*a):active.append(1)
    def checkin(*a):active.pop()
    event.listen(engine,'checkout',checkout);event.listen(engine,'checkin',checkin)
    try:
        class CheckedAdapter(SyntheticAdapter):
            def discover(self):
                assert not active
                return super().discover()
            def fetch(self,item):
                assert not active
                return super().fetch(item)
        result=collect_in_phases(factory,CheckedAdapter('status_services_mail'),idempotency_key='short-tx-fixture')
        assert result.new_versions==1
    finally:
        event.remove(engine,'checkout',checkout);event.remove(engine,'checkin',checkin)


def test_article_models_run_outside_database_transactions(factory):
    from tests.test_article_pipeline_v2 import ArticleBatchAdapter,V2Provider
    from journeyplus.sources.collection import collect_in_phases
    from journeyplus.article_operations import process_pending_articles
    with factory.begin() as s:seed_sources(s)
    engine=factory.kw['bind'];active=[]
    def checkout(*a):active.append(1)
    def checkin(*a):active.pop()
    event.listen(engine,'checkout',checkout);event.listen(engine,'checkin',checkin)
    try:
        class CheckedProvider(V2Provider):
            def generate_structured(self,**kw):
                assert not active
                return super().generate_structured(**kw)
        provider=CheckedProvider()
        collected=collect_in_phases(factory,ArticleBatchAdapter([('tx-example','Status match offer',
            'Example Air offers a direct status match to Gold. Apply at https://example-air.test/apply')]),
            idempotency_key='article-model-tx', article_provider=provider)
        result=process_pending_articles(factory,provider,document_ids=collected.document_version_ids)
        assert result.failed==0
        assert {call['model'] for call in provider.calls}=={'TitleScreenBatch','ArticleInterpretation'}
    finally:
        event.remove(engine,'checkout',checkout);event.remove(engine,'checkin',checkin)
