from sqlalchemy import select, func

from journeyplus.article_operations import process_pending_articles
from journeyplus.article_pipeline.briefs import ArticleBriefGenerator
from journeyplus.contracts import read_brief
from journeyplus.models import AnalysisRun, ArticleAnalysisRecord, ArticleBriefRecord, ArticleOpportunityRecord, JobRun
from journeyplus.product.briefs import ProductBriefService
from journeyplus.product.opportunities import PersonalizedMatchService
from tests.test_article_pipeline_v2 import V2Provider, _collect

BODY = 'Example Air offers a direct status match to Gold. Apply at https://example-air.test/apply'


def seed(factory):
    with factory.begin() as s:
        _collect(s, [('merged-copy', 'Original article title', BODY)])


def legacy_extraction(session):
    for job in session.scalars(select(JobRun).where(JobRun.job_type == "generic_article_v2")):
        job.idempotency_key = "old-workflow:" + str(job.id)
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.stage == 'ARTICLE_INTERPRETATION'))
    run.prompt_version = 'generic-article-interpretation-v11'
    run.idempotency_key = run.idempotency_key.replace('generic-article-interpretation-v12-merged-copy', run.prompt_version)
    run.result = {**run.result, 'opportunities': [
        {k: v for k, v in op.items() if k != 'title'} for op in run.result['opportunities']]}


def test_copy_is_from_extraction_and_product_reads_short_brief(session_factory):
    seed(session_factory)
    provider = V2Provider()
    result = process_pending_articles(session_factory, provider)
    assert result.model_calls == 2 and result.brief_model_calls == 0
    assert [c['model'] for c in provider.calls] == ['TitleScreenBatch', 'ArticleInterpretation']
    with session_factory.begin() as s:
        op = s.scalar(select(ArticleOpportunityRecord))
        record = s.get(ArticleBriefRecord, op.current_brief_id)
        extracted = s.scalar(select(AnalysisRun).where(AnalysisRun.stage == 'ARTICLE_INTERPRETATION')).result['opportunities'][0]
        assert record.content['title'] == extracted['title']
        assert record.content['summary'] == extracted['summary']
        assert set(record.content) == {'schema_version', 'fact_set_id', 'title', 'summary', 'source_links'}
        assert str(op.id) == record.content['fact_set_id']
        assert s.get(AnalysisRun, record.analysis_run_id).provider == 'program'
        assert ProductBriefService(s).list().items[0].title == extracted['title']
        assert PersonalizedMatchService(s).detail(op.id).brief.summary == extracted['summary']
        again = ArticleBriefGenerator(s).generate(op)
        assert again.reused and again.record.id == record.id
        assert s.scalar(select(func.count()).select_from(ArticleBriefRecord)) == 1


def test_legacy_publication_is_not_reprocessed_on_upgrade(session_factory):
    seed(session_factory)
    provider = V2Provider()
    process_pending_articles(session_factory, provider)
    with session_factory.begin() as s:
        legacy_extraction(s)
        record = s.scalar(select(ArticleBriefRecord))
        content = dict(record.content)
        content.update(schema_version='1', title_fact_keys=['what_happened'], summary_fact_keys=['what_happened'], key_points=[], caveats=[])
        record.content = content
        record.schema_version = '1'
        assert read_brief(content).title == content['title']
    before = len(provider.calls)
    result = process_pending_articles(session_factory, provider)
    assert result.selected == result.model_calls == 0
    assert len(provider.calls) == before
    with session_factory() as s:
        assert ProductBriefService(s).list().items


def test_legacy_pending_copy_assembled_without_reextracting(session_factory):
    seed(session_factory)
    provider = V2Provider()
    process_pending_articles(session_factory, provider)
    with session_factory.begin() as s:
        legacy_extraction(s)
        op = s.scalar(select(ArticleOpportunityRecord))
        op.current_brief_id = None
        for record in s.scalars(select(ArticleBriefRecord)):
            s.delete(record)
    result = process_pending_articles(session_factory, provider)
    assert result.briefs == 1 and result.model_calls == 0
    with session_factory() as s:
        assert s.scalar(select(ArticleBriefRecord)).content['title'] == 'Original article title'
        assert s.scalar(select(func.count()).select_from(ArticleAnalysisRecord)) == 1


def test_new_extraction_without_title_cannot_publish(session_factory):
    seed(session_factory)
    class MissingTitle(V2Provider):
        def generate_structured(self, **kwargs):
            result = super().generate_structured(**kwargs)
            if kwargs['output_model'].__name__ == 'ArticleInterpretation':
                result.opportunities[0].title = None
            return result
    result = process_pending_articles(session_factory, MissingTitle())
    assert result.failed == 1 and result.briefs == 0 and result.brief_model_calls == 0
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ArticleBriefRecord)) == 0
