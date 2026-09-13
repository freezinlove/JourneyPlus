"""Article model phases operate on detached, versioned input snapshots."""
from types import SimpleNamespace
from sqlalchemy import select
from journeyplus.models import (AnalysisRun,ArticleAnalysisRecord,ArticleOpportunityRecord,ArticleBriefRecord,
                                DocumentVersion,SourceItem)
from journeyplus.contracts import AnalysisStage,RunStatus
from journeyplus.article_pipeline.screening import BatchTitleScreener
from journeyplus.article_pipeline.interpretation import ArticleInterpreter,ARTICLE_INTERPRETATION_PROMPT_VERSION
from journeyplus.article_pipeline.briefs import ArticleBriefGenerator,ARTICLE_BRIEF_PROMPT_VERSION
from journeyplus.contracts import Brief
from journeyplus.article_pipeline.contracts import ArticleInterpretation


def screen_in_phases(factory,provider,document_ids):
    with factory() as s:
        screener=BatchTitleScreener(s,provider);pending=[];baseline={}
        for did in document_ids:
            doc=s.get(DocumentVersion,did);item=s.get(SourceItem,doc.source_item_id)
            baseline[did]=(item.title,item.published_at)
            run=s.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key==screener._idempotency_key(doc,item)))
            if not run or not run.result:
                pending.append((SimpleNamespace(id=did),SimpleNamespace(title=item.title),None))
    renderer=BatchTitleScreener(None,provider);rendered={}
    for start in range(0,len(pending),renderer._batch_size):
        results,error=renderer.render_chunk(pending[start:start+renderer._batch_size])
        rendered.update({did:(result,error) for did,result in results.items()})
    with factory.begin() as s:
        docs=[s.get(DocumentVersion,did) for did in document_ids]
        for doc in docs:
            item=s.get(SourceItem,doc.source_item_id)
            if baseline[doc.id]!=(item.title,item.published_at):raise ValueError('Article metadata changed during screening')
        result=BatchTitleScreener(s,provider).screen(docs,rendered=rendered)
        s.flush();s.expunge_all()
        return result


def interpret_in_phases(factory,provider,document_id):
    with factory() as s:
        doc=s.get(DocumentVersion,document_id);item=s.get(SourceItem,doc.source_item_id)
        key=f'{AnalysisStage.ARTICLE_INTERPRETATION}:{doc.id}:{provider.metadata.config_version}:{ARTICLE_INTERPRETATION_PROMPT_VERSION}'
        run=s.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key==key))
        analysis=s.scalar(select(ArticleAnalysisRecord).where(ArticleAnalysisRecord.analysis_run_id==run.id)) if run else None
        cached=bool(run and run.result and run.status!=RunStatus.FAILED and (analysis is None or analysis.status!='NEEDS_REVIEW'))
        baseline=(item.title,item.published_at)
        cached_result=ArticleInterpretation.model_validate(run.result) if cached else None
        s.expunge_all()
    rendered=(cached_result,None) if cached else ArticleInterpreter(None,provider).render(doc,item)
    with factory.begin() as s:
        doc=s.get(DocumentVersion,document_id);item=s.get(SourceItem,doc.source_item_id)
        if baseline!=(item.title,item.published_at):raise ValueError('Article metadata changed during interpretation')
        result=ArticleInterpreter(s,provider).interpret(doc,rendered=rendered)
        s.flush();s.expunge_all()
        return result


def article_brief_in_phases(factory,provider,opportunity_id):
    with factory() as s:
        op=s.get(ArticleOpportunityRecord,opportunity_id)
        from journeyplus.knowledge.source_documents import source_links
        document_links=source_links(s,op)
        baseline=op.fact_signature
        key=f'{AnalysisStage.ARTICLE_BRIEF}:{op.id}:{baseline}:{provider.metadata.config_version}:{ARTICLE_BRIEF_PROMPT_VERSION}'
        run=s.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key==key))
        cached=Brief.model_validate(run.result) if run and run.result else None
        s.expunge_all()
    try:
        rendered=cached or ArticleBriefGenerator(None,provider).render(op,document_links=document_links)
        with factory.begin() as s:
            op=s.scalar(select(ArticleOpportunityRecord).where(ArticleOpportunityRecord.id==opportunity_id).with_for_update())
            if op.fact_signature!=baseline:raise ValueError('Article facts changed during brief generation')
            result=ArticleBriefGenerator(s,provider).generate(op,rendered=rendered)
            op.status='DRAFT';s.flush();s.expunge_all()
            return result
    except Exception:
        with factory.begin() as s:
            op=s.get(ArticleOpportunityRecord,opportunity_id)
            if op and op.fact_signature==baseline:op.status='NEEDS_REVIEW'
        raise
