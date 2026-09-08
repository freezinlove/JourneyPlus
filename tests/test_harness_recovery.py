import asyncio
from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from journeyplus.agent.composition import compose
from journeyplus.agent.adapters.models import RunCheckpoint
from journeyplus.agent.harness.contracts import ModelEvent,ToolDefinition,ToolResult
from journeyplus.models import now_utc
from tests.test_harness_runtime import FakeModel,Echo,echo,call,answer


def test_cancel_inflight_model_keeps_terminal_state(session_factory):
    class Slow(FakeModel):
        async def stream(self,*args):
            yield ModelEvent(type='text_delta',text='Starting')
            await asyncio.sleep(60)
            yield ModelEvent(type='turn_end',finish_reason='stop')
    async def scenario():
        runtime,store=compose(session_factory,Slow([]));w=store.create();r=store.start(w['id'],'hello','one',0)
        task=asyncio.create_task(runtime.run(r['run_id']))
        await asyncio.sleep(.05)
        runtime.cancel(r['run_id']);await task
        assert store.events(w['id'],r['run_id'])[1]=='CANCELED'
        assert store.read(w['id'])['revision']==2
    asyncio.run(scenario())


def test_old_lease_cannot_start_tools_or_finish_new_worker(session_factory):
    runtime,store=compose(session_factory,FakeModel([]));w=store.create();r=store.start(w['id'],'hello','one',0)
    old,new=str(uuid4()),str(uuid4())
    assert store.claim_run(r['run_id'],old)
    assert store.claim_run(r['run_id'],new) is None
    with session_factory.begin() as s:s.get(RunCheckpoint,UUID(r['run_id'])).heartbeat_at=now_utc()-timedelta(seconds=46)
    assert store.claim_run(r['run_id'],new)
    with pytest.raises(ValueError):store.tool_intent(r['run_id'],old,{'call_id':'x','name':'echo','arguments':{'value':'hello'}},'READ')
    store.finish_run(r['run_id'],old,'FAILED')
    assert store.events(w['id'],r['run_id'])[1]=='RUNNING'


def test_three_independent_reads_run_concurrently_and_preserve_pair_order(session_factory):
    active=0;maximum=0
    async def handler(args,ctx):
        nonlocal active,maximum
        active+=1;maximum=max(maximum,active);await asyncio.sleep(.03);active-=1
        return ToolResult(data={'value':args.value})
    batch=[{'type':'tool_call_ready','call_id':str(i),'name':'echo','arguments':{'value':str(i)}} for i in range(3)]+[{'type':'turn_end','finish_reason':'tool_calls'}]
    model=FakeModel([batch,answer()]);runtime,store=compose(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler)])
    w=store.create();r=store.start(w['id'],'hello','one',0);asyncio.run(runtime.run(r['run_id']))
    assert maximum==3
    assert [p.call_id for m in model.inputs[-1] for p in m.content if p.type=='tool_result']==['0','1','2']


def test_inflight_snapshot_and_cursor_share_delivery_boundary(session_factory):
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    runtime,store=compose(session_factory,FakeModel([]));w=store.create();r=store.start(w['id'],'hello','one',0)
    owner=str(uuid4());store.claim_run(r['run_id'],owner)
    mid=str(uuid4())
    store.append_and_publish(r['run_id'],'text_delta',{'message_id':mid,'text':'one'})
    snap=store.read(w['id'])
    assert snap['messages'][-1]['content'][0]['text']=='one'
    assert snap['runs'][-1]['last_seq']==2
    store.append_and_publish(r['run_id'],'text_delta',{'message_id':mid,'text':' two'})
    replay=store.events(w['id'],r['run_id'],snap['runs'][-1]['last_seq'])[0]
    assert [e['payload']['text'] for e in replay]==[' two']
    store.append_message(r['run_id'],owner,ModelMessage(id=mid,role='assistant',content=[Part(type='text',text='one two')]))
    store.finish_run(r['run_id'],owner,'COMPLETED')
    latest=store.read(w['id'],limit=1)
    assert len(latest['messages'])==1 and latest['messages'][0]['id']==mid
    older=store.read(w['id'],cursor=latest['next_cursor'],limit=1)
    assert older['messages'][0]['role']=='user' and older['next_cursor'] is None


def test_crash_after_effect_commit_before_tool_result_keeps_receipt(session_factory):
    from dataclasses import replace
    from tests.test_harness_memory import setup
    runtime,store,w,r,ctx,args=setup(session_factory)
    with session_factory() as s:turn=str(s.get(RunCheckpoint,UUID(r['run_id'])).turn_id)
    ctx=replace(ctx,turn_id=turn)
    result=runtime.services['user_memory'].write(args,ctx)
    # No tool_result is recorded: simulate death immediately after business COMMIT.
    assert store.completed_operations(r['run_id'])==[result.data['operation_ref']]
    assert store.read(w['id'])['operations'][0]['operation_ref']==result.data['operation_ref']
    runtime.cancel(r['run_id'])
    asyncio.run(runtime.run(r['run_id']))
    assert store.events(w['id'],r['run_id'])[1]=='CANCELED'
    assert store.completed_operations(r['run_id'])==[result.data['operation_ref']]


def test_reads_flush_before_writes_and_following_reads(session_factory):
    timeline=[];active=0
    async def read(args,ctx):
        nonlocal active
        active+=1;timeline.append('read-start:'+args.value)
        await asyncio.sleep(.02)
        timeline.append('read-end:'+args.value);active-=1
        return ToolResult(data={'value':args.value})
    async def write(args,ctx):
        assert active==0
        timeline.append('write:'+args.value)
        await asyncio.sleep(.01)
        return ToolResult(data={'value':args.value})
    selections=[('read','a'),('read','b'),('read','c'),('write','d'),('write','e'),('read','f')]
    batch=[{'type':'tool_call_ready','call_id':value,'name':name,'arguments':{'value':value}} for name,value in selections]+[{'type':'turn_end','finish_reason':'tool_calls'}]
    runtime,store=compose(session_factory,FakeModel([batch,answer()]),[
        ToolDefinition('read','Read',Echo,read),ToolDefinition('write','Write',Echo,write,effect='USER_WRITE')])
    w=store.create();r=store.start(w['id'],'exercise independent effects','one',0)
    asyncio.run(runtime.run(r['run_id']))
    assert max(timeline.index('read-end:'+value) for value in 'abc')<timeline.index('write:d')
    assert timeline.index('write:d')<timeline.index('write:e')<timeline.index('read-start:f')


def test_expired_owner_cannot_finish_and_recovery_rejects_model_change(session_factory):
    model=FakeModel([]);model.configuration_id='new-model'
    runtime,store=compose(session_factory,model)
    w=store.create();r=store.start(w['id'],'hello','one',0);owner=str(uuid4())
    store.claim_run(r['run_id'],owner)
    with session_factory.begin() as s:
        cp=s.get(RunCheckpoint,UUID(r['run_id']))
        cp.heartbeat_at=now_utc()-timedelta(seconds=46)
        cp.remaining_budget={'model_configuration_id':'old-model'}
    store.finish_run(r['run_id'],owner,'COMPLETED')
    assert store.events(w['id'],r['run_id'])[1]=='RUNNING'
    asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    assert status=='PARTIAL' and any(e['payload'].get('code')=='MODEL_CONFIGURATION_CHANGED' for e in events)
    assert model.inputs==[]
