import json
from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import select
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.knowledge.contracts import KnowledgeDraft,PriceDraft
from journeyplus.knowledge.publication import PublicationService,CatalogService
from journeyplus.knowledge.refresh import KnowledgeRefreshService
from journeyplus.knowledge.models import Activity,ActivityBrief,ActivityObservationState
from tests.test_workspace import factory
from tests.test_knowledge import fixture_draft


class DraftProvider(SequenceAIProvider):
    def __init__(self,draft):super().__init__([]);self.draft=draft
    def generate_structured(self, *, user_prompt, output_model, **kwargs):
        self.calls.append({})
        context=json.loads(user_prompt);data=self.draft.model_dump(mode='json')
        return output_model.model_validate({'facts':data['facts'],'options':data['options']})


def test_real_refresh_contract_publishes_then_reuses_without_model(factory):
    with factory.begin() as s:draft,_,_=fixture_draft(s)
    provider=DraftProvider(draft);service=KnowledgeRefreshService(factory,provider)
    first=service._process(draft.activity_id,draft.documents,force=False)
    again=service._process(draft.activity_id,draft.documents,force=False)
    assert first['status']=='PUBLISHED' and again['status']=='REUSED'
    assert first['version_id']==again['version_id'] and len(provider.calls)==1
    with factory() as s:
        assert s.scalar(select(ActivityBrief)).status=='READY'
        assert s.get(ActivityObservationState,draft.activity_id).freshness=='FRESH'


def test_failed_new_extraction_keeps_published_version(factory):
    with factory.begin() as s:draft,_,_=fixture_draft(s)
    service=KnowledgeRefreshService(factory,DraftProvider(draft))
    first=service._process(draft.activity_id,draft.documents,force=False)
    failed=KnowledgeRefreshService(factory,SequenceAIProvider([TimeoutError('fixture timeout')]))
    with pytest.raises(TimeoutError):failed._process(draft.activity_id,draft.documents,force=True)
    with factory() as s:
        assert str(s.get(Activity,draft.activity_id).current_version_id)==first['version_id']
        assert s.get(ActivityObservationState,draft.activity_id).freshness=='INCOMPLETE'


def test_nonzero_amount_must_be_in_cited_source(factory):
    with factory.begin() as s:
        draft,_,_=fixture_draft(s);data=draft.model_dump(mode='json')
        data['options'][0]['prices'][0]['amount']='999'
        with pytest.raises(ValueError,match='absent'):PublicationService(s).publish(KnowledgeDraft.model_validate(data))
        assert s.get(Activity,draft.activity_id).current_version_id is None


def test_free_without_currency_is_representable_but_needs_explicit_evidence(factory):
    with factory.begin() as s:
        draft,_,_=fixture_draft(s);data=draft.model_dump(mode='json')
        data['options'][0]['prices'][0].update(amount='0',currency=None)
        parsed=KnowledgeDraft.model_validate(data)
        with pytest.raises(ValueError,match='explicit free'):PublicationService(s).publish(parsed)
    with pytest.raises(ValueError,match='currency'):
        PriceDraft.model_validate({**data['options'][0]['prices'][0],'amount':'1'})


def test_catalog_format_aliases_do_not_merge_distinct_programs(factory):
    with factory.begin() as s:
        c=CatalogService(s);a=c.program('Club Avolta');t=c.tier(a.id,'Club Avolta Gold status')
        assert c.program('ClubAvolta').id==a.id
        assert c.tier(a.id,'Gold').id==t.id
        assert c.program('Avolta Other').id!=a.id


def test_materials_disclose_activity_conditions_and_exact_mapping_ids(factory):
    from journeyplus.knowledge.reads import ActivityReadService
    with factory.begin() as s:
        draft,_,ev=fixture_draft(s)
        data=draft.model_dump(mode='json')
        data['facts']['conditions']={'items':[{'condition_id':'once','topic':'PRIOR_PARTICIPATION','operator':'TEXT','value':'once','known_state':'KNOWN','raw_text':'once per customer','evidence_ids':[str(ev.id)]}]}
        draft=KnowledgeDraft.model_validate(data);PublicationService(s).publish(draft)
        result=ActivityReadService(s).materials(selector={'ref':str(draft.activity_id)},question='匹配到哪个等级，资格条件是什么？')
        facts=result['data']['facts']
        assert any(f['subject_ref']==str(draft.activity_id) and f['field']=='conditions' for f in facts)
        mapping=next(f for f in facts if f['field']=='mappings')
        assert len(mapping['value'])==2
        assert {x['tier_ref'] for x in result['data']['catalog']} >= {str(m.target_tier_id) for m in draft.options[0].mappings}


def test_model_short_refs_resolve_without_copying_database_ids(factory):
    from journeyplus.knowledge.workflow import KnowledgeWorkflow
    with factory.begin() as s:draft,_,_=fixture_draft(s)
    class ShortProvider(SequenceAIProvider):
        def generate_structured(self, *, user_prompt, output_model, **kwargs):
            context=json.loads(user_prompt)
            evidence=context['sources'][0]['sections'][0]['evidence_id']
            assert evidence.startswith('K') and len(evidence)<8
            schema=json.dumps(output_model.model_json_schema())
            assert '"format": "uuid"' not in schema
            return output_model.model_validate({'facts':{'title':'Example','summary':{'known_state':'KNOWN','value':'source-bound summary','evidence_ids':[evidence]}},'options':[]})
    workflow=KnowledgeWorkflow(factory,ShortProvider([]))
    prepared=workflow.prepare(draft.activity_id,draft.documents)
    result=workflow.extract(prepared)
    assert result.activity_id==draft.activity_id and isinstance(result.facts.summary.evidence_ids[0],UUID)


def test_known_amount_cannot_be_attached_to_another_target(factory):
    with factory.begin() as s:
        draft,_,_=fixture_draft(s);data=draft.model_dump(mode='json')
        data['options'][0]['prices'][1].update(amount='100',raw_text='B Silver: EUR 100')
        with pytest.raises(ValueError,match='target tier'):
            PublicationService(s).publish(KnowledgeDraft.model_validate(data))


def test_lookup_accepts_program_reference_and_ignores_query_filler(factory):
    from journeyplus.knowledge.reads import ActivityReadService
    with factory.begin() as s:
        draft,_,_=fixture_draft(s);PublicationService(s).publish(draft)
        p=s.get(__import__('journeyplus.knowledge.models',fromlist=['MembershipProgram']).MembershipProgram,draft.options[0].mappings[0].target_program_id)
        reader=ActivityReadService(s)
        assert reader.locate(ref=str(p.id))[0].id==draft.activity_id
        assert reader.locate(text=f'Other Gold to {p.display_name} status match')[0].id==draft.activity_id


def test_brief_failure_keeps_facts_fresh_and_retries_without_extraction(factory,monkeypatch):
    import journeyplus.knowledge.briefs as briefs
    with factory.begin() as s:draft,_,_=fixture_draft(s)
    original=briefs.generate_pending_briefs
    def fail(*args):raise RuntimeError('brief fixture failure')
    monkeypatch.setattr(briefs,'generate_pending_briefs',fail)
    provider=DraftProvider(draft);service=KnowledgeRefreshService(factory,provider)
    result=service._process(draft.activity_id,draft.documents,force=False)
    assert result['status']=='PUBLISHED' and result['briefs']['status']=='FAILED'
    with factory() as s:
        assert s.get(ActivityObservationState,draft.activity_id).freshness=='FRESH'
        assert s.scalar(select(ActivityBrief)).status=='FAILED'
    monkeypatch.setattr(briefs,'generate_pending_briefs',original)
    assert service._process(draft.activity_id,draft.documents,force=False)['status']=='REUSED'
    assert len(provider.calls)==1
    with factory() as s:assert s.scalar(select(ActivityBrief)).status=='READY'


def test_evidence_only_update_does_not_create_change_news(factory):
    from journeyplus.models import DocumentVersion,now_utc
    from journeyplus.knowledge.sources import section_document,create_evidence
    from uuid import uuid4
    with factory.begin() as s:
        draft,doc,old_ev=fixture_draft(s);first=PublicationService(s).publish(draft)
        body=doc.normalized_body+'\nAdditional source note.\n'
        new=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=body,normalized_body=body,content_type='text/markdown',storage_mode='FULL',raw_hash=str(uuid4()),normalized_hash=str(uuid4()),parser_version='fixture',fetched_at=now_utc())
        s.add(new);s.flush();sections=section_document(s,new.id);ev=create_evidence(s,sections[1].id,sections[1].body)
        data=json.loads(draft.model_dump_json().replace(str(doc.id),str(new.id)).replace(str(old_ev.id),str(ev.id)))
        data.update(base_version_id=str(first.id),extraction_key='new-source-only')
        second=PublicationService(s).publish(KnowledgeDraft.model_validate(data))
        assert second.id!=first.id and second.fact_hash==first.fact_hash
        assert s.scalar(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==second.id,ActivityBrief.brief_kind=='UPDATE')) is None


@pytest.mark.parametrize('url,source,published,reason', [
    ('https://loyaltylobby.com/old/','loyaltylobby_feed','2026-09-05T15:59:59+00:00','HISTORICAL_LOYALTYLOBBY'),
    ('https://loyaltylobby.com/new/','loyaltylobby_feed','2026-09-06T00:00:00+08:00',None),
    ('https://www.loyaltylobby.com/unknown/','loyaltylobby_feed',None,'PUBLICATION_DATE_UNKNOWN'),
    ('https://redirect.example/article','loyaltylobby_feed','2026-08-01T00:00:00+00:00','HISTORICAL_LOYALTYLOBBY'),
    ('https://clubavolta.statusmatch.com/faq','gmail',None,None),
    ('https://loyaltylobby.com.example.org/','gmail',None,None),
])
def test_article_scope_respects_publication_date_and_preserves_official_backfill(url,source,published,reason):
    from datetime import datetime
    from types import SimpleNamespace
    from journeyplus.knowledge.ingestion_scope import article_scope_reason
    item=SimpleNamespace(canonical_url=url,source_id=source,published_at=datetime.fromisoformat(published) if published else None)
    assert article_scope_reason(item)==reason


def test_historical_article_force_refresh_and_backfill_do_not_create_activity(factory):
    from journeyplus.models import (SourceItem, DocumentVersion, AnalysisRun, ArticleAnalysisRecord,
                                    ArticleOpportunityRecord, now_utc)
    from journeyplus.knowledge.migration import backfill_identity_and_sources
    from datetime import datetime, UTC
    from uuid import uuid4
    with factory.begin() as s:
        draft,_,_=fixture_draft(s)
        doc=s.get(DocumentVersion,draft.documents[0].document_version_id)
        item=s.get(SourceItem,doc.source_item_id)
        item.canonical_url='https://loyaltylobby.com/2026/08/24/old/'
        item.published_at=datetime(2026,8,24,tzinfo=UTC)
        run=AnalysisRun(idempotency_key=str(uuid4()),document_version_id=doc.id,stage='article',status='COMPLETED',
            input_version='test',provider='test',model='test',model_config_version='test',prompt_version='test',schema_version='test')
        s.add(run);s.flush()
        analysis=ArticleAnalysisRecord(document_version_id=doc.id,source_item_id=item.id,analysis_run_id=run.id,
            input_version='test',label='STATUS_MATCH',confidence=1,reason='test',status='READY',content_signature='test')
        s.add(analysis);s.flush()
        opportunity=ArticleOpportunityRecord(analysis_id=analysis.id,opportunity_index=0,program='Must not create',
            summary='old',visibility_until_at=now_utc(),visibility_policy='test',facts={},fact_signature='test')
        s.add(opportunity);s.flush();oid=opportunity.id
    provider=SequenceAIProvider([])
    result=KnowledgeRefreshService(factory,provider).article(oid,force=True)
    assert result['reason']=='HISTORICAL_LOYALTYLOBBY' and provider.calls==[]
    with factory.begin() as s:
        migrated=backfill_identity_and_sources(s)
        assert migrated['excluded_articles']==1 and migrated['excluded_documents']==1
        assert s.scalar(select(Activity).where(Activity.identity_key==f'legacy:article_opportunities:{oid}')) is None


def test_closed_home_replays_after_watch_removal_and_preserves_history(factory):
    from journeyplus.models import StatusEvent, SourceItem, DocumentVersion, now_utc
    from journeyplus.knowledge.models import ActivityKnowledgeVersion
    from uuid import uuid4
    with factory.begin() as s:
        draft,_,_=fixture_draft(s)
        event=StatusEvent(created_from_key=str(uuid4()),program='Closure fixture',summary='test')
        s.add(event);s.flush()
        activity=s.get(Activity,draft.activity_id)
        activity.identity_key=f'legacy:status_events:{event.id}'
        old=PublicationService(s).publish(draft);old_id=old.id
        item=s.get(SourceItem,s.get(DocumentVersion,draft.documents[0].document_version_id).source_item_id)
        body='This status match offer has ended.'
        doc=DocumentVersion(source_item_id=item.id,canonical_url=item.canonical_url,normalized_body=body,
            content_type='text/plain',storage_mode='FULL',raw_hash=str(uuid4()),normalized_hash=str(uuid4()),
            parser_version='test',fetched_at=now_utc())
        s.add(doc);s.flush();event.closure_document_version_id=doc.id;eid=event.id
    provider=SequenceAIProvider([]);service=KnowledgeRefreshService(factory,provider)
    first=service.closed_event(eid);again=service.closed_event(eid)
    assert first['status']=='PUBLISHED' and again['status']=='REUSED' and not provider.calls
    with factory() as s:
        detail=__import__('journeyplus.knowledge.reads',fromlist=['ActivityReadService']).ActivityReadService(s)
        assert detail.detail(draft.activity_id)['facts']['lifecycle']['value']=='CLOSED'
        assert detail.detail(draft.activity_id)['options']==[]
        assert len(detail.detail(draft.activity_id,old_id)['options'])==1
        assert s.get(ActivityKnowledgeVersion,old_id).status=='PUBLISHED'


@pytest.mark.parametrize('home,faq_error,expected', [
    ('# Recently ended offers\n\nOld price EUR 100.',None,'官方页面没有可发布的当前正文'),
    ('Apply now.','timeout','官方三页不完整或本次检查失败，保留已发布版本'),
])
def test_incomplete_or_entirely_historical_official_source_never_reaches_model(factory,home,faq_error,expected):
    from journeyplus.models import StatusEvent, StatusMatchWatch, StatusMatchWatchPage, DocumentVersion, now_utc
    from uuid import uuid4
    with factory.begin() as s:
        draft,_,_=fixture_draft(s)
        source_doc=s.get(DocumentVersion,draft.documents[0].document_version_id)
        event=StatusEvent(created_from_key=str(uuid4()),program='Official fixture',summary='test')
        s.add(event);s.flush()
        watch=StatusMatchWatch(host='fixture.statusmatch.com',current_event_id=event.id)
        s.add(watch);s.flush()
        for kind in ['activity','faq','terms']:
            body=home if kind=='activity' else 'Current terms.'
            doc=DocumentVersion(source_item_id=source_doc.source_item_id,canonical_url=f'https://fixture.statusmatch.com/{kind}',
                normalized_body=body,content_type='text/plain',storage_mode='FULL',raw_hash=str(uuid4()),
                normalized_hash=str(uuid4()),parser_version='test',fetched_at=now_utc())
            s.add(doc);s.flush()
            s.add(StatusMatchWatchPage(watch_id=watch.id,page_kind=kind,canonical_url=doc.canonical_url,
                current_document_version_id=doc.id,last_error=faq_error if kind=='faq' else None))
    provider=SequenceAIProvider([])
    result=KnowledgeRefreshService(factory,provider).official('fixture.statusmatch.com')
    assert result['status']=='DEFERRED' and result['reason']==expected and not provider.calls
