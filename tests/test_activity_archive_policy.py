"""Lifecycle acceptance through production readers, registry and runtime ports."""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, inspect

from journeyplus.lifecycle.service import BEIJING_TZ, advance_lifecycles, refresh_event_lifecycle
from journeyplus.lifecycle.visibility import effective_status, contributes, is_ended
from journeyplus.article_pipeline.lifecycle import advance_article_lifecycles
from journeyplus.models import (StatusEvent, FactSetRecord, BriefRecord, DocumentVersion,
    StatusMatchWatch, ArticleOpportunityRecord, ArticleBriefRecord)
from journeyplus.contracts import FactSet
from journeyplus.statusmatch.project_workflow import (process_pending_statusmatch_projects,
    process_statusmatch_project_in_phases, StatusMatchProjectWorkflow)
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.knowledge.workflow_knowledge import WorkflowActivityReader
from journeyplus.product.briefs import ProductBriefService
from journeyplus.product.opportunities import PersonalizedMatchService
from journeyplus.product.api import create_product_app
from journeyplus.product.knowledge_server import create_knowledge_app
from journeyplus.agent.composition import compose_business
from journeyplus.agent.harness.contracts import ModelMessage, Part, ToolResult
from tests.test_agent_workflow_reads import original_factory, seed, context, call
from tests.test_statusmatch_project_workflow import (
    ProjectProvider, _seed_active_watch, _extraction, _responses, PageFetcher)
from journeyplus.statusmatch.service import monitor_statusmatch_watches
from tests.test_harness_runtime import FakeModel, answer

NOW = datetime(2026, 9, 13, 12, tzinfo=BEIJING_TZ)


def record(*, article=False, **changes):
    values = dict(application_start_at=None, application_deadline_at=None,
                  archived_at=None, lifecycle_status='ACTIVE')
    if article:
        values.update(visibility_until_at=NOW+timedelta(days=180),
                      visibility_policy='DEFAULT_180_DAYS', archive_reason=None)
    return SimpleNamespace(**{**values, **changes})


@pytest.mark.parametrize('seconds,status', [(-1,'ACTIVE'),(0,'ACTIVE'),(.000001,'EXPIRED')])
@pytest.mark.parametrize('article', [False,True])
def test_inclusive_deadline_exact_instant(article, seconds, status):
    row = record(article=article, application_deadline_at=NOW)
    if article:
        row.visibility_until_at=NOW; row.visibility_policy='EXPLICIT_DEADLINE'
    current = NOW+timedelta(seconds=seconds)
    assert effective_status(row,now=current)==status
    assert contributes(row,now=current)==(status=='ACTIVE')


@pytest.mark.parametrize('changes,status,visible', [
    ({},'UNKNOWN',True),  # No deadline is not an invented timeout.
    ({'application_start_at':NOW+timedelta(days=1)},'UNKNOWN',False),
    ({'application_start_at':NOW},'UNKNOWN',True),
    ({'archived_at':NOW},'EXPIRED',False),
    ({'lifecycle_status':'EXPIRED'},'EXPIRED',False),
    ({'application_deadline_at':NOW-timedelta(days=1)},'EXPIRED',False),
    ({'application_start_at':NOW+timedelta(days=2),'application_deadline_at':NOW+timedelta(days=1)},'UNKNOWN',False),
])
def test_official_no_deadline_start_and_archive(changes,status,visible):
    row=record(**changes)
    assert effective_status(row,now=NOW)==status
    assert contributes(row,now=NOW)==visible


@pytest.mark.parametrize('reason,status', [('STALE_180D','STALE'),('DEADLINE_EXPIRED','EXPIRED'),('MANUAL','ARCHIVED')])
def test_article_archive_does_not_invent_official_closure(reason,status):
    assert effective_status(record(article=True,archived_at=NOW,archive_reason=reason),now=NOW)==status


def official(factory):
    with factory.begin() as session:
        watch = _seed_active_watch(session); watch_id=watch.id
    mapping=dict(source_program='Example Air',source_tiers=['Gold'],target_tier='Gold',availability='AVAILABLE')
    provider=ProjectProvider([_extraction(narrative_mappings=[mapping])])
    result=process_pending_statusmatch_projects(factory,provider)
    assert result.succeeded==1 and result.model_calls==1, result
    return UUID(result.projects[0].event_id), watch_id


def expire(factory,identity,*,article=False,stored=False):
    with factory.begin() as session:
        row=session.get(ArticleOpportunityRecord if article else StatusEvent,identity)
        past=datetime.now(BEIJING_TZ)-timedelta(days=2)
        if article:
            row.visibility_until_at=past
        else:
            row.application_deadline_at=past
        if stored:
            row.archived_at=past
            if article: row.archive_reason='STALE_180D'
            else: row.lifecycle_status='EXPIRED'


@pytest.mark.parametrize('stored',[False,True])
def test_official_all_readers_before_and_after_maintenance(original_factory,session_factory,stored):
    identity,_=official(original_factory)
    with original_factory() as session:
        row=session.get(StatusEvent,identity); version=row.current_fact_set_id
        before=WorkflowActivityReader(session).detail(identity)
        assert MembershipGraphService(session).build().edges
        counts={model.__tablename__:session.scalar(select(func.count()).select_from(model))
                for model in (StatusEvent,FactSetRecord,BriefRecord,DocumentVersion)}
    tables=set(inspect(original_factory.kw['bind']).get_table_names())
    expire(original_factory,identity,stored=stored)
    for maintenance in (False,True):
        if maintenance:
            with original_factory.begin() as session: advance_lifecycles(session)
        with original_factory() as session:
            assert not MembershipGraphService(session).build().edges
            assert not WorkflowActivityReader(session).locate()
            assert not ProductBriefService(session).list().items
            archived=ProductBriefService(session).list(include_archived=True).items
            assert len(archived)==1 and archived[0].lifecycle_status=='EXPIRED'
            after=WorkflowActivityReader(session).detail(identity,version)
            assert after['card']['lifecycle_status']=='EXPIRED'
            for key in ('facts','options','sources','briefs','brief_url'): assert before[key]==after[key]
            assert not PersonalizedMatchService(session).read().opportunities
            assert counts=={model.__tablename__:session.scalar(select(func.count()).select_from(model))
                for model in (StatusEvent,FactSetRecord,BriefRecord,DocumentVersion)}
        runtime,store,ctx=context(session_factory,original_factory)
        validated,_=runtime.ports.registry.validate('activity.read',{'selector':{'ref':f'activity:{identity}@{version}'},'view':'detail'})
        result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
        assert result.error and not result.data
        with pytest.raises(LookupError):
            runtime.services['knowledge'].read_reference(f'activity:{identity}@{version}')
    assert tables==set(inspect(original_factory.kw['bind']).get_table_names())
    for client in (TestClient(create_product_app(original_factory)),TestClient(create_knowledge_app(original_factory))):
        response=client.get(f'/v2/activities/{identity}',params={'version_ref':str(version)})
        assert response.status_code==200, response.text
        assert response.json()['card']['lifecycle_status']=='EXPIRED'
    client=TestClient(create_product_app(original_factory))
    assert client.get('/v1/briefs').json()['items']==[]
    assert client.get('/v1/briefs?include_archived=true').json()['items'][0]['lifecycle_status']=='EXPIRED'
    assert client.get(f'/v1/match-opportunities/{version}').json()['lifecycle_status']=='EXPIRED'


def test_article_stale_reads_maintenance_and_manual_archive(original_factory):
    identity=seed(original_factory)
    with original_factory.begin() as session:
        row=session.get(ArticleOpportunityRecord,identity)
        brief=ArticleBriefRecord(opportunity_id=row.id,analysis_run_id=uuid4(),input_version=str(row.id),version=1,
            schema_version='statusmatch-brief-1',content={'schema_version':'statusmatch-brief-1',
            'fact_set_id':str(row.id),'title':'Test match','summary':'Summary','source_links':[]})
        session.add(brief);session.flush();row.current_brief_id=brief.id
        original=json.dumps(row.facts,sort_keys=True)
    expire(original_factory,identity,article=True)
    for maintenance in (False,True):
        with original_factory.begin() as session:
            if maintenance: advance_article_lifecycles(session)
            row=session.get(ArticleOpportunityRecord,identity)
            assert effective_status(row)=='STALE'
            assert row.application_deadline_at is None
            assert not WorkflowActivityReader(session).locate()
            assert not ProductBriefService(session).list().items
            assert ProductBriefService(session).list(include_archived=True).items[0].lifecycle_status=='STALE'
            assert WorkflowActivityReader(session).detail(identity)['card']['lifecycle_status']=='STALE'
            assert json.dumps(row.facts,sort_keys=True)==original
    with original_factory.begin() as session:
        row=session.get(ArticleOpportunityRecord,identity)
        row.visibility_until_at=datetime.now(BEIJING_TZ)+timedelta(days=365)
        assert is_ended(row)  # Extending freshness never restores an archived record.


@pytest.mark.parametrize('stored',[False,True])
def test_reopened_watch_owns_new_event_and_only_new_brief(original_factory,stored):
    old_id,watch_id=official(original_factory)
    with original_factory() as session:
        old=WorkflowActivityReader(session).detail(old_id)
    expire(original_factory,old_id,stored=stored)
    # Same active watch, same host, changed HOME: real monitored and phased production.
    responses=_responses();responses['https://example.statusmatch.com/'] += '<p>A new application period is open.</p>'
    with original_factory.begin() as session: monitor_statusmatch_watches(session,PageFetcher(responses))
    provider=ProjectProvider([_extraction(eligibility='New conditions')])
    result=process_pending_statusmatch_projects(original_factory,provider)
    assert result.succeeded==1 and result.model_calls==1, result
    new_id=UUID(result.projects[0].event_id)
    assert new_id!=old_id
    with original_factory() as session:
        new=session.get(StatusEvent,new_id)
        previous=session.get(StatusEvent,old_id)
        assert session.get(StatusMatchWatch,watch_id).current_event_id==new_id
        assert new.current_fact_set_id!=previous.current_fact_set_id
        assert session.get(FactSetRecord,new.current_fact_set_id).version==1
        assert len(WorkflowActivityReader(session).history(new_id)['versions'])==1
        after=WorkflowActivityReader(session).detail(old_id)
        for key in ('facts','briefs','sources','brief_url'): assert old[key]==after[key]
        assert [row.id for row in WorkflowActivityReader(session).locate()]==[new_id]
        # Expired facts cannot be revived by refresh with a deadline-less extraction.
        if stored:
            refresh_event_lifecycle(previous,FactSet.model_validate(session.get(FactSetRecord,new.current_fact_set_id).facts))
            assert is_ended(previous)
    repeat=process_pending_statusmatch_projects(original_factory,ProjectProvider([]))
    assert repeat.model_calls==0 and repeat.selected==0


def test_agent_artifact_cursor_section_route_and_display_cannot_bypass_archive(original_factory,session_factory):
    identity=seed(original_factory)
    runtime,store,ctx=context(session_factory,original_factory)
    ctx.artifact_port=runtime.ports.artifacts;ctx.authorization_port=runtime.ports.workspace
    detail=call(runtime,ctx,'activity.read',{'selector':{'ref':f'activity:{identity}'},'view':'detail'})
    activity=detail.data['activities'][0]
    refs=[activity['material_ref'],activity['material_ref']+'#section:facts']
    # Stored route snapshot deliberately includes old facts but has the normal typed association.
    route=store.artifacts.put(ctx.workspace_id,'ROUTES',{'routes':{'one':{'step_refs':['one']}},
        'steps':{'one':{'activity_ref':str(identity),'version_ref':activity['version_ref'],'to':'Example Rewards Gold'}}})
    refs.extend([route,route+'#step:one',route+'#route:one'])
    alias=store.artifacts.put(ctx.workspace_id,'MATERIAL',{'summary':'cached secret'},source_refs=[refs[0]])
    refs.append(alias)
    expire(original_factory,identity,article=True)
    for ref in refs:
        with pytest.raises(LookupError): ctx.artifact_port.read(ctx.workspace_id,ref)
        with pytest.raises(LookupError): ctx.authorization_port.validate_reference(ctx.workspace_id,ref)
    for name,args in [
        ('activity.read',{'selector':{'ref':activity['ref']},'section_refs':[refs[1]],'view':'detail'}),
        ('workspace.read',{'kind':'artifact','refs':[alias]}),
        ('display.present',{'blocks':[{'type':'route_graph','object_refs':[route+'#route:one']}]}),
    ]:
        validated,error=runtime.ports.registry.validate(name,args)
        assert not error, (name,error)
        result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
        assert result.error and not result.data, result
    cached=runtime.ports.views.result(ctx.workspace_id,ToolResult(data={'cached':'secret'},artifact_refs=[alias]))
    assert cached.error.code=='ACTIVITY_ENDED' and not cached.data
    # Raw persisted artifact remains readable by the human/history store.
    assert store.artifacts.read(ctx.workspace_id,alias)['payload']['summary']=='cached secret'


def test_real_runtime_rechecks_prior_turn_before_modelport(original_factory,session_factory):
    identity=seed(original_factory)
    batches=[[
        {'type':'tool_call_ready','call_id':'read','name':'activity.read',
         'arguments':{'selector':{'ref':f'activity:{identity}'},'view':'detail'}},
        {'type':'turn_end','finish_reason':'tool_calls'}], answer('Previous activity narrative'), answer('No current activity')]
    model=FakeModel(batches)
    runtime,store=compose_business(session_factory,model,read_factory=original_factory)
    workspace=store.create();wid=workspace['id']
    first=store.start(wid,'读取活动','first',0)
    asyncio.run(runtime.run(first['run_id']))
    assert store.events(wid,first['run_id'])[1]=='COMPLETED'
    assert 'Example Rewards' in json.dumps([m.model_dump(mode='json') for m in model.inputs[-1]])
    expire(original_factory,identity,article=True)
    second=store.start(wid,'现在还有什么','second',store.read(wid)['revision'])
    asyncio.run(runtime.run(second['run_id']))
    assert store.events(wid,second['run_id'])[1]=='COMPLETED'
    visible=json.dumps([m.model_dump(mode='json') for m in model.inputs[-1]])
    assert 'Example Rewards' not in visible and 'Previous activity narrative' not in visible
    assert 'ACTIVITY_ENDED' in visible
    history=runtime.ports.workspace.history(wid,limit=50)
    assert 'Previous activity narrative' not in json.dumps(history)
    assert 'Previous activity narrative' in json.dumps(store.history(wid,limit=50))


def test_ended_unchanged_home_and_faq_edits_do_not_create_new_period(original_factory):
    identity,_=official(original_factory)
    expire(original_factory,identity)
    assert process_pending_statusmatch_projects(original_factory,ProjectProvider([])).selected==0
    responses=_responses();responses['https://example.statusmatch.com/faq'] += '<p>Minor FAQ edit.</p>'
    with original_factory.begin() as session: monitor_statusmatch_watches(session,PageFetcher(responses))
    result=process_pending_statusmatch_projects(original_factory,ProjectProvider([]))
    assert result.selected==0 and result.model_calls==0
    with original_factory() as session:
        assert session.scalar(select(func.count()).select_from(StatusEvent))==1


def test_closure_during_model_request_never_publishes_into_old_event(original_factory):
    identity,watch_id=official(original_factory)
    with original_factory() as session: before=WorkflowActivityReader(session).detail(identity)
    class ClosingProvider(ProjectProvider):
        def generate_structured(self,**kwargs):
            expire(original_factory,identity,stored=True)
            return super().generate_structured(**kwargs)
    with pytest.raises(ValueError,match='changed during extraction'):
        process_statusmatch_project_in_phases(original_factory,ClosingProvider([_extraction()]),watch_id)
    with original_factory() as session:
        after=WorkflowActivityReader(session).detail(identity)
        assert before['version_ref']==after['version_ref']
        assert before['facts']==after['facts'] and before['briefs']==after['briefs']


def test_archive_affects_notes_and_history_refs_but_retains_saved_records(original_factory,session_factory):
    identity=seed(original_factory)
    model=FakeModel([[
        {'type':'tool_call_ready','call_id':'read','name':'activity.read',
         'arguments':{'selector':{'ref':f'activity:{identity}'},'view':'detail'}},
        {'type':'turn_end','finish_reason':'tool_calls'}],answer('Prior route')])
    runtime,store=compose_business(session_factory,model,read_factory=original_factory)
    workspace=store.create();wid=workspace['id']
    run=store.start(wid,'Read activity','first',0);asyncio.run(runtime.run(run['run_id']))
    messages=store.load_context_index(wid)['messages']
    user=next(m for m in messages if m.role=='user')
    note=store.artifacts.put(wid,'NOTE',{'content':'Example Rewards old conditions','source_message_refs':[user.id]})
    linked=store.artifacts.put(wid,'MATERIAL',{'summary':'Derived old conditions'},source_refs=[user.id])
    expire(original_factory,identity,article=True)
    assert runtime.ports.artifacts.read(wid,note)['payload'].get('notice')
    with pytest.raises(LookupError):runtime.ports.artifacts.read(wid,linked)
    assert store.artifacts.read(wid,note)['payload']['content']=='Example Rewards old conditions'
    last=next(m for m in reversed(messages) if m.role=='assistant')
    page=runtime.ports.workspace.history(wid,refs=[last.id],limit=1)
    assert 'Prior route' not in json.dumps(page)


def test_repeated_maintenance_is_idempotent_and_no_deadline_official_stays_open(original_factory):
    identity,_=official(original_factory)
    with original_factory.begin() as session:
        row=session.get(StatusEvent,identity)
        advance_lifecycles(session,now=datetime.now(BEIJING_TZ)+timedelta(days=1000))
        assert row.archived_at is None
        assert not is_ended(row)
    expire(original_factory,identity)
    with original_factory.begin() as session:
        first=advance_lifecycles(session); timestamp=session.get(StatusEvent,identity).archived_at
        second=advance_lifecycles(session,now=datetime.now(BEIJING_TZ)+timedelta(days=1))
        assert first.updated==1 and second.updated==0
        assert session.get(StatusEvent,identity).archived_at==timestamp


def test_cache_and_graph_change_at_deadline_without_any_database_write(original_factory,monkeypatch):
    identity,_=official(original_factory)
    with original_factory.begin() as session:
        row=session.get(StatusEvent,identity)
        row.application_deadline_at=NOW; row.lifecycle_status='ACTIVE'
    from journeyplus.knowledge import workflow_knowledge
    instant=NOW
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(workflow_knowledge,'datetime',Clock)
    with original_factory() as session:
        at=workflow_knowledge.WorkflowKnowledgePort.snapshot_values(session,'routes.evaluate')
        assert MembershipGraphService(session,now=instant).build().edges
        original_updated=session.get(StatusEvent,identity).updated_at
    instant=NOW+timedelta(microseconds=1)
    with original_factory() as session:
        after=workflow_knowledge.WorkflowKnowledgePort.snapshot_values(session,'routes.evaluate')
        assert not MembershipGraphService(session,now=instant).build().edges
        row=session.get(StatusEvent,identity)
        assert row.archived_at is None and row.lifecycle_status=='ACTIVE' and row.updated_at==original_updated
    assert at!=after


def test_unrelated_current_activity_and_new_material_remain_available(original_factory,session_factory):
    old=seed(original_factory); current=seed(original_factory)
    runtime,store,ctx=context(session_factory,original_factory)
    ctx.artifact_port=runtime.ports.artifacts;ctx.authorization_port=runtime.ports.workspace
    old_read=call(runtime,ctx,'activity.read',{'selector':{'ref':f'activity:{old}'},'view':'detail'})
    good_read=call(runtime,ctx,'activity.read',{'selector':{'ref':f'activity:{current}'},'view':'detail'})
    expire(original_factory,old,article=True)
    good=good_read.data['activities'][0]['material_ref']
    assert ctx.artifact_port.read(ctx.workspace_id,good)['payload']['ref']==str(current)
    result=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'},'view':'overview'})
    assert len(result.data['activities'])==1
    assert str(current) in result.data['activities'][0]['ref']
    old_artifact=old_read.data['activities'][0]['material_ref']
    cursor=store.artifacts.put(ctx.workspace_id,'MATERIAL',{'activities':old_read.data['activities'],'activity_query_hash':'obsolete'})
    with pytest.raises(LookupError):ctx.artifact_port.read(ctx.workspace_id,cursor)
    with pytest.raises(LookupError):ctx.artifact_port.read(ctx.workspace_id,old_artifact)


@pytest.mark.parametrize('policy,expected', [('DEFAULT_180_DAYS','STALE'),('MANUAL_OVERRIDE','ARCHIVED'),('EXPLICIT_DEADLINE','EXPIRED')])
def test_article_visibility_read_and_archive_share_one_decision(original_factory,policy,expected):
    identity=seed(original_factory)
    with original_factory.begin() as session:
        row=session.get(ArticleOpportunityRecord,identity)
        row.visibility_policy=policy
        row.visibility_until_at=NOW-timedelta(days=1)
        assert row.application_deadline_at is None
        assert effective_status(row,now=NOW)==expected
        advance_article_lifecycles(session,now=NOW)
        assert row.archived_at is not None
        assert effective_status(row,now=NOW)==expected


def test_reopen_with_previously_seen_homepage_uses_new_job_namespace(original_factory):
    first,watch=official(original_factory)
    original_responses=_responses()
    second_responses=_responses()
    second_responses['https://example.statusmatch.com/'] += '<p>Another open period.</p>'
    event_ids=[first]
    for responses in (second_responses,original_responses):
        expire(original_factory,event_ids[-1],stored=True)
        with original_factory.begin() as session:
            monitor_statusmatch_watches(session,PageFetcher(responses))
        run=process_pending_statusmatch_projects(original_factory,ProjectProvider([_extraction()]))
        assert run.succeeded==1 and run.model_calls==1,run
        event_ids.append(UUID(run.projects[0].event_id))
        assert process_pending_statusmatch_projects(original_factory,ProjectProvider([])).selected==0
    assert len(set(event_ids))==3
    with original_factory() as session:
        for identity in event_ids:
            row=session.get(StatusEvent,identity)
            assert session.get(FactSetRecord,row.current_fact_set_id).version==1
