"""Behavioral regressions for provider-independent contracts and evidence retention."""
import asyncio
from dataclasses import replace
from uuid import UUID
from journeyplus.models import StatusHolding
from journeyplus.knowledge.models import MembershipProgram, MembershipTier
from journeyplus.agent.tools.contracts import RoutesInput, WaitingInput, BlockSelection
from journeyplus.agent.tools.routes import evaluate
from journeyplus.agent.services.presentations import build_block
from journeyplus.agent.services.query_lineage import differences
from journeyplus.agent.harness.contracts import ToolDefinition, ModelMessage, Part, ToolResult
from journeyplus.agent.harness.context import project
from tests.test_harness_tools import context
from tests.test_harness_memory import setup
from tests.test_harness_runtime import FakeModel, Echo, echo, call, answer
from tests.test_knowledge_routes import edge


def test_resolution_candidates_are_not_catalog_absence(session_factory):
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        p=MembershipProgram(canonical_key='sample',display_name='Sample Airways Club',category='AIRLINE')
        s.add(p);s.flush()
        s.add(MembershipTier(program_id=p.id,canonical_key='gold',display_name='Gold'))
    with runtime.services['knowledge'].read() as s:
        resolve=runtime.services['identities'].resolve
        result=resolve(s,{'program_name':'Sample Airways','tier_name':'Gold'},require_tier=True)
        assert result['resolution_state']=='CANDIDATES'
        assert result['candidates'][0]['tier_name']=='Gold'
        assert resolve(s,{'ref':result['candidates'][0]['ref']},require_tier=True)['resolution_state']=='BOUND'
        assert resolve(s,{'program_name':'Sample Airways Club'},require_tier=True)['resolution_state']=='TIER_REQUIRED'
        assert resolve(s,{'program_name':'unindexed unrelated'})['resolution_state']=='NOT_INDEXED'
        assert resolve(s,{'ref':'holding:00000000-0000-0000-0000-000000000000'})['resolution_state']=='INVALID_REFERENCE'


def test_original_statement_survives_incorrect_extraction_and_workspace_expiry(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    args.identity.program_name='俱乐部'  # Deliberately lossy model extraction.
    result=runtime.services['user_memory'].write(args,ctx)
    source=result.data['after']['source_record']
    assert source['original_statements'][0]['text']=='请保存我的测试俱乐部金卡。'
    assert source['extracted_identity']['program_name']=='俱乐部'
    assert source['interpretation_verified'] is False
    with session_factory() as s:
        row=s.get(StatusHolding,UUID(result.data['after']['ref'].removeprefix('holding:')))
        assert row.source_record==source


def test_unbound_wait_is_saved_but_not_executed_then_can_be_bound(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    service=runtime.services['waiting']
    original=service.manage(WaitingInput(operation='create',query={'sources':{'mode':'none'},'target':{'program_name':'Not Indexed'}}),ctx)
    assert original.data['after']['status']=='NEEDS_RECONFIRMATION'
    assert original.data['after']['readiness']['ready'] is False
    assert service.check()['coverage']['search_performed'] is False
    with session_factory.begin() as s:source,target=edge(s)
    updated=service.manage(WaitingInput(operation='update',goal_ref=original.data['after']['ref'],
        expected_revision=original.data['revision'],query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]},'target':{'ref':'tier:'+str(target)}}),replace(ctx,call_id='update-wait'))
    assert updated.data['after']['status']=='ACTIVE'
    assert service.check()['status']=='RESULT_PENDING'
    assert not runtime.ports.model.inputs


def test_query_lineage_preserves_unmodified_field_origins(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    with session_factory.begin() as s:source,target=edge(s)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]},'constraints':{'free_only':True}}),ctx))
    second=asyncio.run(evaluate(RoutesInput(operation='search',query_ref=first.data['query_ref'],patch={'target':{'ref':'tier:'+str(target)}}),ctx))
    lineage=second.data['query_context']
    assert lineage['parent_query_ref']==first.data['query_ref']
    assert second.data['effective_query']['constraints']['free_only'] is True
    assert lineage['field_origins']['/constraints/free_only']==first.data['query_context']['field_origins']['/constraints/free_only']
    assert any(change['field']=='/target/ref' for change in lineage['changes'])
    replay=asyncio.run(evaluate(RoutesInput(operation='search',query_ref=second.data['query_ref']),ctx))
    assert replay.data['query_context']['changes']==[]
    assert differences({'target':{'ref':'tier:one'}},{'target':None})==[{'field':'/target','before':{'ref':'tier:one'},'after':None}]


def test_comparison_uses_step_snapshot_conditions_and_versions():
    condition={'reason':'Residents of France or Germany only','expected':['France','Germany'],'result':'UNKNOWN'}
    route={'cost':{'state':'KNOWN'},'step_refs':['step:1'],'steps':{'step:1':{'version_ref':'v1','to':'Gold',
        'constraint_checks':[condition],'status_validity':{'known_state':'KNOWN','value':{'kind':'DURATION','months':12}},
        'application_window':{'option':{'known_state':'UNKNOWN'}}}}}
    result=build_block(BlockSelection(type='comparison',object_refs=['route:1'],columns=['conditions','validity','window']),[route])
    value=result['payload']['objects'][0]['data']['comparison_values']
    assert value['conditions'][0]['value']==[condition]
    assert value['validity'][0]['version_ref']=='v1'
    assert value['window'][0]['value']==route['steps']['step:1']['application_window']
    assert result['object_count']==1
    assert 'comparison_values' not in route


def test_context_dedup_preserves_pairs_original_and_latest_observation():
    definition=ToolDefinition('echo','Echo',Echo,echo)
    messages=[ModelMessage(id='user1',role='user',content=[Part(type='text',text='read twice')])]
    for i in range(2):
        result=ToolResult(call_id=str(i),data={'text':'evidence '*300},artifact_refs=['artifact:full'+str(i)],coverage={'complete':True,'full_result_ref':'artifact:full'+str(i)}).model_dump(mode='json')
        messages.extend([ModelMessage(role='assistant',content=[Part(type='tool_call',call_id=str(i),name='echo',arguments={'value':'same'})]),
                         ModelMessage(id='result'+str(i),role='tool',content=[Part(type='tool_result',call_id=str(i),result=result)])])
    view=project(messages,[definition],FakeModel([]).capabilities())
    results=[p.result for m in view for p in m.content if p.type=='tool_result']
    assert results[0]['data']['context_projection']=='duplicate_read'
    assert results[1]['data']['text']=='evidence '*300
    assert messages[2].content[0].result['data']['text']=='evidence '*300
    assert [p.call_id for m in view for p in m.content if p.type=='tool_call']==['0','1']
    assert [p.call_id for m in view for p in m.content if p.type=='tool_result']==['0','1']
    definition.effect='USER_WRITE'
    assert 'context_projection' not in project(messages,[definition],FakeModel([]).capabilities())[2].content[0].result['data']


def test_soft_budget_warning_does_not_disable_necessary_tool(session_factory):
    from journeyplus.agent.composition import compose
    batches=[call(id='one'),call(id='two'),answer()]
    batches[0].insert(-1,{'type':'usage','usage':{'prompt_tokens':5000,'completion_tokens':10}})
    class Inspect(FakeModel):
        async def stream(self,messages,definitions,limits,cancel_token):
            assert limits['tools_allowed']
            async for event in super().stream(messages,definitions,limits,cancel_token):yield event
    model=Inspect(batches)
    runtime,store=compose(session_factory,model,[ToolDefinition('echo','Echo',Echo,echo)])
    runtime.budget_limits={'soft':{'input_tokens':4000},'hard':{'input_tokens':60000}}
    w=store.create();r=store.start(w['id'],'read twice','run',0)
    asyncio.run(runtime.run(r['run_id']))
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    assert len(model.inputs)==3


def test_actual_unconfigured_capability_is_in_model_view(session_factory):
    runtime,store,w,ctx=context(session_factory)
    view=project([ModelMessage(role='user',content=[Part(type='text',text='search')])],runtime.ports.registry.definitions(),FakeModel([]).capabilities())
    assert 'SEARCH_PROVIDER_NOT_CONFIGURED' in str([m.model_dump() for m in view])


def test_recent_evidence_is_not_shrunk_without_context_pressure():
    definition=ToolDefinition('echo','Echo',Echo,echo)
    messages=[ModelMessage(role='user',content=[Part(type='text',text='compare both')])]
    for i in range(2):
        result=ToolResult(data={'text':str(i)+' evidence '*1100},artifact_refs=['artifact:'+str(i)])
        messages.extend([ModelMessage(role='assistant',content=[Part(type='tool_call',call_id=str(i),name='echo',arguments={'value':str(i)})]),
            ModelMessage(role='tool',content=[Part(type='tool_result',call_id=str(i),result=result.model_dump(mode='json'))])])
    view=project(messages,[definition],FakeModel([]).capabilities())
    assert view[2].content[0].result['data']==messages[2].content[0].result['data']


def test_deleted_explicit_holding_suspends_wait_instead_of_crashing(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    with session_factory.begin() as s:
        source,target=edge(s)
        row=StatusHolding(program_key='known',tier_key='gold',program_display_name='Known',tier_display_name='Gold',tier_id=source)
        s.add(row);s.flush();hid=row.id
    service=runtime.services['waiting']
    created=service.manage(WaitingInput(operation='create',query={'sources':{'mode':'explicit','holding_refs':['holding:'+str(hid)]}}),ctx)
    assert created.data['after']['status']=='ACTIVE'
    with session_factory.begin() as s:s.delete(s.get(StatusHolding,hid))
    checked=service.check()
    assert checked['status']=='NEEDS_RECONFIRMATION'
    assert checked['readiness']['issues'][0]['resolution']['resolution_state']=='INVALID_REFERENCE'
    assert checked['coverage']['unresolved_holding_count']==1


def test_final_reserve_accounts_for_new_observation(session_factory):
    from journeyplus.agent.composition import compose
    from journeyplus.agent.harness.budget import estimate
    class Adaptive(FakeModel):
        def __init__(self):super().__init__([]);self.limits=[]
        def estimate_input(self,messages,definitions):return 1000
        def estimate_final_input(self,messages,definitions):
            return estimate([m.model_dump(mode='json') for m in messages])
        async def stream(self,messages,definitions,limits,cancel_token):
            self.inputs.append(messages);self.limits.append(limits)
            for event in (answer('budget-limited final') if not limits['tools_allowed'] else call()):
                from journeyplus.agent.harness.contracts import ModelEvent
                yield ModelEvent(**event)
    model=Adaptive();runtime,store=compose(session_factory,model,[ToolDefinition('echo','Echo',Echo,echo)])
    runtime.budget_limits={'soft':{'input_tokens':5000},'hard':{'input_tokens':6000}}
    w=store.create();r=store.start(w['id'],'read if a result and final response can both fit','test',0)
    asyncio.run(runtime.run(r['run_id']))
    assert len(model.inputs)==1 and model.limits[0]['tools_allowed'] is False
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_failed_identity_query_remains_patchable_without_losing_constraints(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    with session_factory.begin() as s:source,target=edge(s)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'explicit','identities':[{'program_name':'Unresolved Source','tier_name':'Gold'}]},
        'target':{'ref':'tier:'+str(target)},'constraints':{'max_amount':'100','currency':'USD'}}),ctx))
    assert first.error and first.coverage['search_performed'] is False
    assert store.artifacts.read(w['id'],first.data['query_ref'])['kind']=='QUERY'
    second=asyncio.run(evaluate(RoutesInput(operation='search',query_ref=first.data['query_ref'],patch={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}),ctx))
    assert not second.error
    assert second.data['effective_query']['constraints']['max_amount']=='100'
    assert second.data['effective_query']['target']['ref']=='tier:'+str(target)
    assert second.data['query_context']['parent_query_ref']==first.data['query_ref']


def test_user_receipt_exposes_original_statement_not_verified_extraction(session_factory):
    from journeyplus.agent.adapters.transport import result_events
    runtime,store,w,r,ctx,args=setup(session_factory)
    args.identity.program_name='俱乐部'
    result=runtime.services['user_memory'].write(args,ctx)
    payload=result_events(result)[0][1]
    assert '名称待核对' in payload['summary']
    assert payload['original_statements'][0]['text']=='请保存我的测试俱乐部金卡。'
