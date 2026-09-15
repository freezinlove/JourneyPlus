import asyncio
from uuid import UUID
from journeyplus.agent.harness.contracts import DTO, ModelEvent, Capabilities, ToolDefinition, ToolResult
from journeyplus.agent.composition import compose
from journeyplus.agent.adapters.models import RunCheckpoint, ToolCall
from sqlalchemy import select


class FakeModel:
    def __init__(self, batches):self.batches=iter(batches);self.inputs=[]
    def capabilities(self):return Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096)
    async def stream(self,messages,definitions,limits,cancel_token):
        self.inputs.append(messages)
        for event in next(self.batches):yield ModelEvent(**event)


def answer(text='done'):
    return [{'type':'text_delta','text':text},{'type':'turn_end','finish_reason':'stop'}]


def call(name='echo',value='hi',id='call-1'):
    return [{'type':'tool_call_ready','call_id':id,'name':name,'arguments':{'value':value}},{'type':'turn_end','finish_reason':'tool_calls'}]


class Echo(DTO):value:str
async def echo(args,context):return ToolResult(data={'value':args.value})


def execute(factory,model,definitions=()):
    runtime,store=compose(factory,model,definitions)
    workspace=store.create()
    run=store.start(workspace['id'],'hello','client-1',0)
    asyncio.run(runtime.run(run['run_id']))
    return store,workspace,run


def test_zero_tool_answer(session_factory):
    store,w,r=execute(session_factory,FakeModel([answer('Hello')]))
    assert store.read(w['id'])['messages'][-1]['content'][0]['text']=='Hello'
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_registered_detail_capacity_preserves_large_atomic_evidence(session_factory):
    class Input(DTO):view:str
    body='evidence '*1900
    async def read(args,ctx):return ToolResult(data={'section':{'text':body,'qualification':'UNKNOWN'}})
    model=FakeModel([[{'type':'tool_call_ready','call_id':'detail','name':'documents.read','arguments':{'view':'detail'}},
                      {'type':'turn_end','finish_reason':'tool_calls'}],answer()])
    definition=ToolDefinition('documents.read','Read documents',Input,read,
        operation_result_max_bytes={'detail':24000},result_budget_field='view')
    store,w,r=execute(session_factory,model,[definition])
    result=next(p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result')
    assert result['data']['section']=={'text':body,'qualification':'UNKNOWN'}
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_more_than_three_model_calls_and_tool_pairing(session_factory):
    model=FakeModel([call(value=str(i),id=str(i)) for i in range(4)]+[answer()])
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,echo)])
    assert len(model.inputs)==5
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    final=model.inputs[-1]
    assert [p.call_id for m in final for p in m.content if p.type=='tool_call']==[str(i) for i in range(4)]
    assert [p.call_id for m in final for p in m.content if p.type=='tool_result']==[str(i) for i in range(4)]


def test_accumulated_tokens_do_not_force_finalization(session_factory):
    batches=[call(value=str(i),id=str(i)) for i in range(2)]+[answer()]
    for index,batch in enumerate(batches):
        batch.insert(-1,{'type':'usage','usage':{'input':900 if index<2 else 200,'output':20}})
    class Model(FakeModel):
        limits=[]
        async def stream(self,messages,definitions,limits,cancel_token):
            self.limits.append(limits)
            async for event in super().stream(messages,definitions,limits,cancel_token):yield event
        def estimate_input(self,messages,definitions):return 1000 if len(self.inputs)<2 else 1500
        def estimate_final_input(self,messages,definitions):return 200
    model=Model(batches);seen=[]
    async def handler(args,ctx):
        seen.append(args.value)
        return ToolResult(data={'value':args.value})
    runtime,store=compose(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler)])
    runtime.budget_limits={'soft':{'input_tokens':2500},'hard':{'input_tokens':3000}}
    w=store.create();r=store.start(w['id'],'read two values then answer','one',0)
    asyncio.run(runtime.run(r['run_id']))
    assert seen==['0','1'] and len(model.inputs)==3
    assert model.limits[-1]['tools_allowed'] is True
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    with session_factory() as session:
        assert session.get(RunCheckpoint,UUID(r['run_id'])).remaining_budget['input_tokens']==2000


def test_unknown_tool_returns_to_model(session_factory):
    model=FakeModel([call('missing'),answer('I can answer directly')])
    store,w,r=execute(session_factory,model)
    result=[p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result'][0]
    assert result['error']['code']=='UNKNOWN_TOOL'
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_partial_arguments_never_execute(session_factory):
    model=FakeModel([[{'type':'tool_call_delta','call_id':'x','name':'echo','arguments_fragment':'{"value":'}, {'type':'turn_end','finish_reason':'error'}],answer()])
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,echo)])
    with session_factory() as s:assert not list(s.scalars(select(ToolCall)))


def test_artifact_scope_and_idempotent_start(session_factory):
    runtime,store=compose(session_factory,FakeModel([]))
    a,b=store.create(),store.create()
    ref=store.artifacts.put(a['id'],'NOTE',{'note':'private'})
    import pytest
    with pytest.raises(LookupError):store.artifacts.read(b['id'],ref)
    run=store.start(a['id'],'hello','same',0)
    assert store.start(a['id'],'hello','same',0)==run
    with pytest.raises(ValueError):store.start(a['id'],'different','same',0)


def test_provider_failure_preserves_partial_text_without_format_retry(session_factory):
    from journeyplus.agent.harness.contracts import ModelUnavailable
    class Unavailable(FakeModel):
        async def stream(self,*args):
            self.inputs.append(args[0])
            yield ModelEvent(type='text_delta',text='Already received text')
            raise ModelUnavailable(400,'Arrearage')
    model=Unavailable([]);runtime,store=compose(session_factory,model)
    workspace=store.create();run=store.start(workspace['id'],'hello','one',0)
    asyncio.run(runtime.run(run['run_id']))
    events,status=store.events(workspace['id'],run['run_id'])
    assert status=='PARTIAL' and len(model.inputs)==1
    assert any(event['payload'].get('provider_code')=='Arrearage' for event in events)
    assert store.read(workspace['id'])['messages'][-1]['metadata']['interrupted'] is True


def test_repeated_read_reuses_same_snapshot_without_stopping(session_factory):
    seen=[]
    async def handler(args,ctx):
        seen.append(args.value)
        return ToolResult(data={'value':args.value})
    model=FakeModel([call(id=str(i)) for i in range(5)]+[answer()])
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler,snapshot=lambda a,c:'v1')])
    assert seen==['hi']
    assert len(model.inputs)==6
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_changed_snapshot_allows_same_arguments_to_make_progress(session_factory):
    state={'version':1,'calls':0}
    async def handler(args,ctx):
        state['calls']+=1
        return ToolResult(data={'version':state['version']})
    class Model(FakeModel):
        async def stream(self,*args):
            state['version']+=1
            async for event in super().stream(*args):yield event
    model=Model([call(id=str(i)) for i in range(3)]+[answer()])
    definition=ToolDefinition('echo','Echo',Echo,handler,snapshot=lambda args,ctx:str(state['version']))
    store,w,r=execute(session_factory,model,[definition])
    assert state['calls']==3
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_context_capacity_stops_explicitly_and_preserves_evidence(session_factory):
    class SmallModel(FakeModel):
        def capabilities(self):return Capabilities(native_tools=True,streaming=True,context_window=8192,max_output=4096)
    model=SmallModel([answer()])
    runtime,store=compose(session_factory,model)
    workspace=store.create();original='长证据'*2000
    run=store.start(workspace['id'],original,'capacity',0)
    asyncio.run(runtime.run(run['run_id']))
    events,status=store.events(workspace['id'],run['run_id'])
    assert status=='PARTIAL' and 'CONTEXT_CAPACITY' in str(events)
    assert not model.inputs
    assert store.load_context_index(workspace['id'])['messages'][0].content[0].text==original


class Delivery(DTO):
    complete: bool = False


def test_final_delivery_ends_only_successful_exclusive_batches(session_factory):
    # Continuation choice, error, partial result and mixed tool batches all
    # retain a subsequent model call; two successful final displays do not.
    for complete, status, mixed, count, expected in [
        (True, 'OK', False, 1, 1), (False, 'OK', False, 1, 2),
        (True, 'ERROR', False, 1, 2), (True, 'PARTIAL', False, 1, 2),
        (True, 'OK', True, 1, 2), (True, 'OK', False, 2, 1),
    ]:
        async def deliver(args, context):
            if status == 'ERROR':
                return ToolResult.failure('INVALID_ARGUMENT', 'Wrong reference')
            return ToolResult(status=status, data={'delivered': True})
        batch=[{'type':'text_delta','text':'查询结论和图一起交付。'}]
        batch += [{'type':'tool_call_ready','call_id':str(i),'name':'deliver','arguments':{'complete':complete}} for i in range(count)]
        if mixed:
            batch.append({'type':'tool_call_ready','call_id':'read','name':'echo','arguments':{'value':'more facts'}})
        batch.append({'type':'turn_end','finish_reason':'tool_calls'})
        model=FakeModel([batch,answer('继续处理结果')])
        definition=ToolDefinition('deliver','Deliver',Delivery,deliver,effect='WORKSPACE_WRITE',
            completes_turn=lambda args,result:args.complete)
        store,w,r=execute(session_factory,model,[definition,ToolDefinition('echo','Read',Echo,echo)])
        assert len(model.inputs)==expected, (complete,status,mixed,count)
        assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
        results=[p for m in store.load_context_index(w['id'])['messages'] for p in m.content if p.type=='tool_result']
        assert len(results)==count+int(mixed)
        with session_factory() as s:
            checkpoint=s.get(RunCheckpoint,UUID(r['run_id']))
            assert bool(checkpoint.remaining_budget.get('delivery_complete')) == (expected==1)


def test_cancellation_after_delivery_does_not_report_completed(session_factory):
    async def deliver(args,ctx):
        ctx.cancel_token.set()
        return ToolResult(data={'delivered':True})
    model=FakeModel([[{'type':'tool_call_ready','call_id':'delivery','name':'deliver','arguments':{'complete':True}},
                      {'type':'turn_end','finish_reason':'tool_calls'}]])
    store,w,r=execute(session_factory,model,[ToolDefinition('deliver','Deliver',Delivery,deliver,
        effect='WORKSPACE_WRITE',completes_turn=lambda args,result:args.complete)])
    assert store.events(w['id'],r['run_id'])[1]=='CANCELED'
    assert len(model.inputs)==1


def test_recovered_completed_delivery_does_not_call_model_again(session_factory):
    async def deliver(args,ctx):return ToolResult(data={'delivered':True})
    runtime,store=compose(session_factory,FakeModel([]),[ToolDefinition('deliver','Deliver',Delivery,deliver,
        effect='WORKSPACE_WRITE',completes_turn=lambda args,result:args.complete)])
    w=store.create();r=store.start(w['id'],'show result','recovered',0)
    with session_factory.begin() as s:
        checkpoint=s.get(RunCheckpoint,UUID(r['run_id']))
        checkpoint.phase='READY_MODEL'
        checkpoint.remaining_budget={'delivery_complete':True}
    asyncio.run(runtime.run(r['run_id']))
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    assert not runtime.ports.model.inputs


def test_model_timing_persisted_outside_model_context(session_factory):
    model=FakeModel([answer('Hello')])
    store,w,r=execute(session_factory,model)
    events,status=store.events(w['id'],r['run_id'])
    timings=[e['payload'] for e in events if e['type']=='model.timing']
    assert status=='COMPLETED' and len(timings)==1
    assert timings[0]['attempt']==1 and timings[0]['harness_elapsed_ms']>=0
    assert 'model.timing' not in str(model.inputs)
    from journeyplus.agent.adapters.persistence import SessionStore
    reloaded=SessionStore(session_factory)
    assert any(e['type']=='model.timing' for e in reloaded.events(w['id'],r['run_id'])[0])


def test_disabled_timing_keeps_normal_answer_without_diagnostic_events(session_factory):
    from types import SimpleNamespace
    model=FakeModel([answer('Hello')])
    model.config=SimpleNamespace(model_timing_enabled=False)
    store,w,r=execute(session_factory,model)
    events,status=store.events(w['id'],r['run_id'])
    assert status=='COMPLETED'
    assert not any(e['type']=='model.timing' for e in events)
    assert store.read(w['id'])['messages'][-1]['content'][0]['text']=='Hello'
