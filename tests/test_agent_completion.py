import asyncio
import json
from journeyplus.agent.harness.contracts import CompletionCheck, ModelMessage, Part
from journeyplus.agent.services.completion import BusinessCompletion
from journeyplus.agent.composition import compose
from tests.test_harness_runtime import FakeModel, answer
from tests.test_harness_tools import context


def test_completion_repair_is_private_and_persisted(session_factory):
    class Check:
        version='test'
        def check(self,text,messages,ctx):
            return CompletionCheck(accepted=text=='fixed',feedback=['missing display receipt'])
    model=FakeModel([answer('unchecked claim'),answer('fixed')])
    runtime,store=compose(session_factory,model)
    runtime.ports.completion=Check()
    w=store.create();r=store.start(w['id'],'show it','one',0)
    asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    assert status=='COMPLETED'
    assert [e['payload']['text'] for e in events if e['type']=='text_delta']==['fixed']
    assert 'unchecked claim' not in json.dumps(store.read(w['id']))
    assert any('COMPLETION_REJECTED' in (p.text or '') for m in model.inputs[-1] for p in m.content)


def test_repeated_rejection_is_partial_not_completed(session_factory):
    class Reject:
        def check(self,*args):return CompletionCheck(accepted=False,feedback=['missing receipt'])
    runtime,store=compose(session_factory,FakeModel([answer('false'),answer('false again')]))
    runtime.ports.completion=Reject()
    w=store.create();r=store.start(w['id'],'show it','one',0)
    asyncio.run(runtime.run(r['run_id']))
    events,status=store.events(w['id'],r['run_id'])
    assert status=='PARTIAL'
    assert not any(e['type']=='text_delta' for e in events)
    from journeyplus.agent.adapters.models import RunCheckpoint
    from uuid import UUID
    with session_factory() as s:
        assert s.get(RunCheckpoint,UUID(r['run_id'])).remaining_budget['completion_failures']==2


def observations(turn,call_id='show',columns=None):
    return [ModelMessage(role='assistant',metadata={'turn_id':turn},content=[Part(type='tool_call',
        call_id=call_id,name='display.present',arguments={})]),
        ModelMessage(role='tool',metadata={'turn_id':turn},content=[Part(type='tool_result',call_id=call_id,
            result={'status':'OK','data':{'presentation_ref':'artifact:receipt','blocks':[
                {'type':'comparison','object_count':2,'columns':columns or ['cost']}]}})])]


def test_missing_columns_or_old_turn_receipt_cannot_satisfy_delivery(session_factory):
    runtime,store,w,ctx=context(session_factory)
    value={'status':'complete','parts':['Comparison'],'deliveries':[
        {'kind':'presentation','call_id':'show','type':'comparison','columns':['conditions'],'minimum_objects':2}]}
    check=BusinessCompletion()
    assert not check.check(json.dumps(value),observations(ctx.turn_id),ctx).accepted
    assert not check.check(json.dumps(value),observations('old-turn',columns=['conditions']),ctx).accepted
    assert check.check(json.dumps(value),observations(ctx.turn_id,columns=['conditions']),ctx).accepted


def test_fact_is_read_from_exact_snapshot_not_model_value(session_factory):
    runtime,store,w,ctx=context(session_factory)
    ref=ctx.artifact_port.put(ctx.workspace_id,'ROUTES',{'cost':{'currency':'USD','amount':'149'}})
    value={'status':'complete','parts':[{'ref':ref,'path':'/cost'}]}
    result=BusinessCompletion().check(json.dumps(value),observations(ctx.turn_id),ctx)
    assert result.accepted and json.loads(result.text)=={'currency':'USD','amount':'149'}
    value['parts'][0]['value']='free'
    assert not BusinessCompletion().check(json.dumps(value),observations(ctx.turn_id),ctx).accepted
    del value['parts'][0]['value']
    value['parts'][0]['path']='/unknown'
    assert not BusinessCompletion().check(json.dumps(value),observations(ctx.turn_id),ctx).accepted


def test_repair_cannot_drop_delivery_and_partial_reports_it(session_factory):
    _,_,_,ctx=context(session_factory)
    draft={'status':'complete','parts':['done'],'deliveries':[{'kind':'presentation','call_id':'missing','columns':['cost']}]}
    old=ModelMessage(role='assistant',content=[Part(type='text',text=json.dumps(draft))],
        metadata={'turn_id':ctx.turn_id,'completion_rejected':True})
    messages=observations(ctx.turn_id)+[old]
    omitted={'status':'complete','parts':['done'],'deliveries':[]}
    assert not BusinessCompletion().check(json.dumps(omitted),messages,ctx).accepted
    omitted.update(status='partial',remaining=['所需比较表尚未交付'])
    result=BusinessCompletion().check(json.dumps(omitted),messages,ctx)
    assert result.accepted and result.partial


def test_last_page_alone_does_not_prove_exhaustive_read(session_factory):
    _,_,_,ctx=context(session_factory)
    messages=[ModelMessage(role='assistant',metadata={'turn_id':ctx.turn_id},content=[
        Part(type='tool_call',call_id='last',name='routes.evaluate',arguments={})]),
        ModelMessage(role='tool',metadata={'turn_id':ctx.turn_id},content=[Part(type='tool_result',call_id='last',result={
            'status':'OK','data':{'query_ref':'artifact:q'},
            'coverage':{'complete':True,'total':10,'offset':8,'returned':2}})])]
    value={'status':'complete','parts':['all'],'deliveries':[{'kind':'coverage','call_id':'last'}]}
    assert not BusinessCompletion().check(json.dumps(value),messages,ctx).accepted


def test_filter_patch_without_change_evidence_does_not_execute(session_factory):
    from tests.test_harness_memory import setup
    from journeyplus.agent.tools.contracts import RoutesInput
    from journeyplus.agent.tools.routes import evaluate
    runtime,store,w,r,ctx,args=setup(session_factory)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'none'},'category':'HOTEL'}),ctx))
    second=asyncio.run(evaluate(RoutesInput(operation='search',query_ref=first.data['query_ref'],patch={'category':None}),ctx))
    assert second.error.code=='CONSTRAINT_CHANGE_REQUIRED'
    assert second.data['query_context']['required_fields']==['/category']
    assert not second.artifact_refs


def test_zero_tool_json_answer_is_not_misclassified_as_protocol(session_factory):
    _,_,_,ctx=context(session_factory)
    assert BusinessCompletion().check('{"example":42}',[],ctx).accepted


def test_constraint_conflict_survives_registered_output_validation(session_factory):
    from tests.test_harness_memory import setup
    from journeyplus.agent.tools.contracts import RoutesInput
    from journeyplus.agent.tools.routes import evaluate
    runtime,store,w,r,ctx,args=setup(session_factory)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'none'},'category':'HOTEL'}),ctx))
    validated,_=runtime.ports.registry.validate('routes.evaluate',{'operation':'search','query_ref':first.data['query_ref'],'patch':{'category':None}})
    result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error.code=='CONSTRAINT_CHANGE_REQUIRED'
    assert result.data['query_context']['required_fields']==['/category']
