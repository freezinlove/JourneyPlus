import asyncio
import pytest
from sqlalchemy import event
import journeyplus.agent.adapters.models
from journeyplus.agent.composition import compose
from journeyplus.agent.harness.contracts import ToolDefinition,ToolResult
from tests.test_harness_runtime import FakeModel,Echo,call,answer


def test_state_only_read_does_not_load_messages(session_factory):
    runtime,store=compose(session_factory,FakeModel([]))
    w=store.create(); statements=[]
    engine=session_factory.kw['bind']
    def record(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:state=store.load_workspace_state(w['id'])
    finally:event.remove(engine,'before_cursor_execute',record)
    assert state['schema_version']==2
    assert not any('workspace_messages' in sql.lower() or 'agent_artifacts' in sql.lower() for sql in statements)


def test_tool_capacity_preparation_is_reused_and_recovery_cache_cleared(session_factory):
    async def read(args,ctx): return ToolResult(data={'text':args.value})
    model=FakeModel([call(),answer()])
    runtime,store=compose(session_factory,model,[ToolDefinition('echo','read',Echo,read)])
    w=store.create(); r=store.start(w['id'],'hello','one',0)
    asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    timings=[e['payload'] for e in events if e['type']=='model.timing']
    assert status=='COMPLETED'
    assert [t['context_reused'] for t in timings]==[False,True]
    assert not runtime.prepared_contexts
    assert any(p.result and p.result['data']=={'text':'hi'} for m in model.inputs[-1] for p in m.content)


def test_access_change_invalidates_prepared_context(session_factory):
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    async def read(args,ctx):return ToolResult(data={'text':args.value})
    model=FakeModel([call(),answer()]); runtime,store=compose(session_factory,model,[ToolDefinition('echo','read',Echo,read)])
    class Views:
        count=0
        def result(self,w,r):return r
        def context(self,w,messages,note,focus):
            self.count+=1
            return messages+[ModelMessage(id='notice',role='system',content=[Part(type='text',text=str(self.count))])],note,focus
    runtime.ports.views=Views()
    w=store.create();r=store.start(w['id'],'hello','one',0);asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    assert status=='COMPLETED'
    assert not any(e['payload']['context_reused'] for e in events if e['type']=='model.timing')


def test_independent_reads_run_together(session_factory):
    arrived=0; gate=asyncio.Event()
    async def read(args,ctx):
        nonlocal arrived
        arrived+=1
        if arrived==2:gate.set()
        await asyncio.wait_for(gate.wait(),1)
        return ToolResult(data={'value':args.value})
    batch=[call(value='a',id='a')[0],call(value='b',id='b')[0],{'type':'turn_end','finish_reason':'tool_calls'}]
    model=FakeModel([batch,answer()]);runtime,store=compose(session_factory,model,[ToolDefinition('echo','read',Echo,read)])
    w=store.create();r=store.start(w['id'],'compare','one',0);asyncio.run(runtime.run(r['run_id']))
    results={p.call_id:p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result'}
    assert results['a']['data']['value']=='a' and results['b']['data']['value']=='b'

def test_overview_retains_summary_and_does_not_expand_details():
    from journeyplus.agent.services.materials import summary
    card={'challenge':'UNKNOWN','eligibility_note':'有地区条件','additional_fee_count':2}
    detail={'ref':'a','name':'activity','version_ref':'v','brief_url':'/news', 'card':card,
            'facts':{'fees':{'known_state':'UNKNOWN'},'limitations':['需要核验']},
            'options':[{'ref':'o','mappings':[{'secret':'not in overview'}]}],
            'sections':{'fact-fees':{},'fact-limitations':{}}}
    result=summary(detail,'artifact:a','overview')
    assert result['summary']==card
    assert result['known_caveats']['limitations']==['需要核验']
    assert result['field_sections']['fees']=='artifact:a#section:fact-fees'
    assert 'facts' not in result and 'options' not in result

def test_schema_cache_is_invalidated_by_structure_and_returns_independent_values():
    from journeyplus.agent.adapters.model import inline_schema
    one={'type':'object','properties':{'a':{'type':'string'}}}
    a=inline_schema(one);a['properties']['a']['type']='number'
    assert inline_schema(one)['properties']['a']['type']=='string'
    two={'type':'object','properties':{'b':{'type':'number'}}}
    assert set(inline_schema(two)['properties'])=={'b'}


def test_state_change_invalidates_cache(session_factory):
    from sqlalchemy.orm.attributes import flag_modified
    from journeyplus.models import AgentInteraction
    from uuid import UUID
    async def read(args,ctx):return ToolResult(data={'value':args.value})
    model=FakeModel([call(),answer()]);runtime,store=compose(session_factory,model,[ToolDefinition('echo','read',Echo,read)])
    real_state=store.load_workspace_state; reads=0
    def state(wid):
        nonlocal reads
        reads+=1
        if reads==3:
            with session_factory.begin() as s:
                w=s.get(AgentInteraction,UUID(wid));w.state={**w.state,'focus':'new focus'};flag_modified(w,'state')
        return real_state(wid)
    store.load_workspace_state=state
    w=store.create();r=store.start(w['id'],'hello','one',0);asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    assert status=='COMPLETED'
    assert not any(e['payload']['context_reused'] for e in events if e['type']=='model.timing')
