"""Validity survives tool boundaries; explicit originals reach the model whole."""
import asyncio
from datetime import date, datetime, UTC, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
from journeyplus.agent.tools.contracts import ActivityInput, HoldingsWriteInput
from journeyplus.agent.tools.projection import model_view_for
from journeyplus.agent.harness.contracts import ToolDefinition, ToolResult, DTO
from journeyplus.models import DocumentVersion
from tests.test_agent_original_runtime import original_factory, migrated, setup
from tests.test_agent_workflow_reads import seed, call
from tests.test_harness_runtime import FakeModel, answer, execute


@pytest.fixture
def clock(monkeypatch):
    import journeyplus.memberships_validity as validity
    moment=[datetime(2026,9,13,15,59,tzinfo=UTC)]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return moment[0].astimezone(tz)
    monkeypatch.setattr(validity,'datetime',Clock)
    return moment


def saved(runtime,ctx):
    return call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{'sources':{'mode':'saved'}}})


def add_holding(factory,expiry,program='Marriott Bonvoy',tier='Platinum'):
    with factory.begin() as s:
        r=WorkflowHolding(program_key=program.lower(),tier_key=tier.lower(),
            program_display_name=program,tier_display_name=tier,valid_until=expiry)
        s.add(r);s.flush();return 'holding:'+str(r.id)


def test_expired_saved_source_is_explained_and_explicit_hypothesis_still_works(migrated,clock):
    seed(migrated)
    ref=add_holding(migrated,date(2026,9,12))
    runtime,store,ctx,_=setup(migrated)
    result=saved(runtime,ctx)
    assert result.status=='EMPTY' and result.data['candidates']==[]
    assert result.coverage['stopped_reason']=='NO_ACTIVE_SAVED_HOLDINGS'
    assert not result.coverage['search_performed']
    assert result.data['source_selection']['excluded_holdings'][0]['holding_ref']==ref
    listed=call(runtime,ctx,'holdings.read',{})
    assert not listed.data['holdings'] and listed.data['membership_state']['expired_count']==1
    one=call(runtime,ctx,'holdings.read',{'holding_refs':[ref]}).data['holdings'][0]
    assert one['validity_status']=='EXPIRED' and not one['usable_as_saved_source']
    hypothesis=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{
        'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}})
    assert hypothesis.data['candidates'][0]['source_mode']=='explicit'
    # Explicitly referring to the saved expired record does not bypass expiry.
    v,_=runtime.ports.registry.validate('routes.evaluate',{'operation':'search','query':{'sources':{'mode':'explicit','holding_refs':[ref]}}})
    failed=asyncio.run(runtime.ports.registry.execute(v,ctx))
    assert failed.error.code=='HOLDING_EXPIRED'


def test_mixed_sources_exclude_only_expired_rows_and_renewal_recovers(migrated,clock):
    seed(migrated)
    active=add_holding(migrated,date(2026,9,13))
    add_holding(migrated,date(2026,9,12),program='Expired Club',tier='Gold')
    runtime,_,ctx,_=setup(migrated)
    result=saved(runtime,ctx)
    assert result.data['candidates'] and result.status=='OK'
    assert result.data['source_selection']['expired_count']==1
    assert result.data['candidates'][0]['source_mode']=='saved'
    row=call(runtime,ctx,'holdings.read',{'holding_refs':[active]}).data['holdings'][0]
    updated=runtime.services['user_memory'].write(HoldingsWriteInput(operation='update',holding_ref=active,
        expected_revision=row['revision'],valid_until='2026-09-12'),ctx)
    assert not updated.error and updated.data['after']['validity_status']=='EXPIRED'
    projected=model_view_for('holdings.write')(updated)
    assert projected.data['entity']['usable_as_saved_source'] is False
    assert saved(runtime,ctx).data['candidates']==[]
    ctx.call_id='renew'
    renewed=runtime.services['user_memory'].write(HoldingsWriteInput(operation='update',holding_ref=active,
        expected_revision=updated.data['revision'],valid_until='2030-01-01'),ctx)
    assert not renewed.error and renewed.data['after']['validity_status']=='CURRENT'
    assert saved(runtime,ctx).data['candidates']


def test_beijing_midnight_invalidates_read_cache_without_database_update(migrated,clock):
    seed(migrated);add_holding(migrated,date(2026,9,13))
    runtime,_,ctx,_=setup(migrated)
    validated,_=runtime.ports.registry.validate('holdings.read',{})
    definition,args,_=validated
    before=definition.snapshot(args,ctx)
    assert call(runtime,ctx,'holdings.read',{}).data['holdings']
    assert saved(runtime,ctx).data['candidates']
    clock[0]+=timedelta(minutes=2)  # Beijing next day, UTC is still September 13.
    assert definition.snapshot(args,ctx)!=before
    assert not call(runtime,ctx,'holdings.read',{}).data['holdings']
    assert saved(runtime,ctx).coverage['stopped_reason']=='NO_ACTIVE_SAVED_HOLDINGS'


def test_no_expiry_is_not_reported_as_permanent_and_empty_is_normal(migrated,clock):
    seed(migrated);runtime,_,ctx,_=setup(migrated)
    empty=saved(runtime,ctx)
    assert empty.data['source_selection']['expired_count']==0
    add_holding(migrated,None)
    row=call(runtime,ctx,'holdings.read',{}).data['holdings'][0]
    assert row['validity_status']=='NO_EXPIRY_RECORDED' and row['usable_as_saved_source']
    assert saved(runtime,ctx).data['candidates']


def test_original_is_whole_article_not_fact_fields_and_missing_body_is_error(migrated):
    seed(migrated)
    text='BEGIN\n'+('Full article paragraph.\n'*4000)+'\n| Tier | Price |\n| Gold | USD 99 |\nFootnote END [apply](https://example.test/apply)'
    with migrated.begin() as s:
        doc=s.scalar(select(DocumentVersion));doc.normalized_body=text;doc_id=doc.id
    runtime,_,ctx,_=setup(migrated)
    overview=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'}})
    ref=overview.data['activities'][0]['ref']
    directory=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'view':'evidence'})
    assert text not in str(directory.data)
    raw=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'view':'original','section_refs':['document:'+str(doc_id)]})
    assert raw.data['documents'][0]['text']==text
    assert raw.data['documents'][0]['complete'] and 'activities' not in raw.data
    with migrated.begin() as s:s.get(DocumentVersion,doc_id).normalized_body=''
    v,_=runtime.ports.registry.validate('activity.read',{'selector':{'ref':ref},'view':'original','section_refs':['document:'+str(doc_id)]})
    failed=asyncio.run(runtime.ports.registry.execute(v,ctx))
    assert failed.error and not failed.data.get('documents')


@pytest.mark.parametrize('too_large',[False,True])
def test_complete_read_crosses_small_tool_budget_but_respects_context_capacity(session_factory,too_large):
    class Input(DTO):view:str
    body='BEGIN '+('full paragraph '* (40000 if too_large else 4000))+' END'
    async def read(args,ctx):return ToolResult(data={'documents':[{'text':body,'complete':True}]})
    model=FakeModel([[{'type':'tool_call_ready','call_id':'original','name':'documents.read','arguments':{'view':'original'}},
                      {'type':'turn_end','finish_reason':'tool_calls'}],answer()])
    definition=ToolDefinition('documents.read','Read a complete archived document',Input,read,
        result_budget_field='view',complete_result_operations=('original',))
    store,w,r=execute(session_factory,model,[definition])
    result=next(p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result')
    if too_large:
        assert result['error']['code']=='CONTEXT_CAPACITY'
        assert not result['data'].get('documents')
    else:
        assert result['data']['documents'][0]['text']==body
        assert result['coverage']['complete'] is True
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_original_selection_requires_one_document_and_rejects_unrelated_source(migrated):
    seed(migrated);runtime,_,ctx,_=setup(migrated)
    selected=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'}}).data['activities'][0]['ref']
    for refs in ([],['document:'+str(uuid4()),'document:'+str(uuid4())]):
        validated,error=runtime.ports.registry.validate('activity.read',{'selector':{'ref':selected},'view':'original','section_refs':refs})
        assert validated is None and error.error.code=='INVALID_ARGUMENT'
    validated,_=runtime.ports.registry.validate('activity.read',{'selector':{'ref':selected},'view':'original','section_refs':['document:'+str(uuid4())]})
    result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error and not result.data.get('documents')


def test_complete_observation_cannot_be_enabled_for_writes():
    from journeyplus.agent.harness.registry import Registry
    class Input(DTO):view:str
    async def write(args,ctx):return ToolResult()
    with pytest.raises(ValueError,match='read-only'):
        Registry().register(ToolDefinition('unsafe.write','write',Input,write,
            effect='USER_WRITE',complete_result_operations=('original',)))
