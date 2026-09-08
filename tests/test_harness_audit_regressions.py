"""Review regressions: expected target behavior, no provider or external DB."""
import asyncio
import json
import time
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from tests.test_harness_runtime import FakeModel, Echo, answer
from tests.test_harness_tools import context
from tests.test_harness_memory import setup
from journeyplus.agent.composition import compose, compose_business
from journeyplus.agent.harness.contracts import ModelMessage, Part, ToolDefinition, ToolResult
from journeyplus.agent.harness.context import bounded_result
from journeyplus.agent.adapters.models import RunCheckpoint
from journeyplus.agent.tools.contracts import DisplayInput, WorkspaceReadInput, ResearchInput
from journeyplus.models import now_utc


def test_recovery_uses_same_bounded_projection(session_factory):
    async def read(args, ctx):
        raise AssertionError('Completed tool must not execute again')
    model = FakeModel([answer()])
    runtime, store = compose(session_factory, model, [ToolDefinition('echo', 'Read', Echo, read)])
    w = store.create(); r = store.start(w['id'], 'read', 'one', 0)
    owner = str(uuid4()); store.claim_run(r['run_id'], owner)
    call = {'call_id': 'c1', 'name': 'echo', 'arguments': {'value': 'x'}}
    store.append_message(r['run_id'], owner, ModelMessage(role='assistant', content=[Part(type='tool_call', **call)]))
    store.tool_intent(r['run_id'], owner, call, 'READ')
    result = ToolResult(call_id='c1', data={'records': [{'text': 'e' * 3000, 'id': i} for i in range(10)]})
    ref = store.tool_result(r['run_id'], owner, call, result)
    normal = bounded_result(result, ref)
    with session_factory.begin() as s:
        s.get(RunCheckpoint, UUID(r['run_id'])).heartbeat_at = now_utc() - timedelta(seconds=46)
    asyncio.run(runtime.run(r['run_id']))
    restored = next(p.result for m in model.inputs[0] for p in m.content if p.type == 'tool_result')
    assert restored == normal.model_dump(mode='json'), {'normal_bytes': len(normal.model_dump_json()), 'restored_bytes': len(json.dumps(restored))}


def test_presentation_call_id_is_scoped_to_turn(session_factory):
    from journeyplus.agent.services.display import present
    runtime, store, w, ctx = context(session_factory)
    first = asyncio.run(present(DisplayInput(blocks=[], next_steps=[{'label':'First','message':'First'}]), replace(ctx, turn_id=str(uuid4()))))
    second = asyncio.run(present(DisplayInput(blocks=[], next_steps=[{'label':'Second','message':'Second'}]), replace(ctx, turn_id=str(uuid4()))))
    assert second.data['next_steps'][0]['label'] == 'Second', second.data
    assert first.data['presentation_ref'] != second.data['presentation_ref']


def test_projection_counts_actual_visible_entries():
    raw = ToolResult(data={'records':[{'id':i,'text':'x'*2000} for i in range(10)]}, coverage={'complete':True,'returned':10,'total':10,'omissions':[]})
    projected = bounded_result(raw, 'artifact:full', max_bytes=8000)
    assert projected.coverage['returned'] == len(projected.data['records']), projected.model_dump()


def test_workspace_artifact_limit_is_honored(session_factory):
    from journeyplus.agent.services.workspace import read
    _, store, w, ctx = context(session_factory)
    refs = [store.artifacts.put(w['id'], 'MATERIAL', {'number':i}) for i in range(3)]
    result = asyncio.run(read(WorkspaceReadInput(kind='artifact',refs=refs,limit=1),ctx))
    assert len(result.data.get('artifacts',result.data.get('sections',[]))) <= 1, result.data
    assert result.next_cursor


def test_imported_quote_needs_current_authorization_quote(session_factory):
    from journeyplus.workspace_models import WorkspaceMessage
    from journeyplus.agent.tools.contracts import Authorization
    runtime, store, w, r, ctx, args = setup(session_factory)
    owner = str(uuid4()); store.claim_run(r['run_id'], owner)
    with session_factory.begin() as s:
        row = s.get(WorkspaceMessage,UUID(args.authorization.message_refs[0]))
        row.content = {**row.content,'metadata':{**row.content['metadata'],'legacy':True}}
    current = ModelMessage(role='user',content=[Part(type='text',text='先不要保存任何东西')])
    store.append_message(r['run_id'],owner,current)
    args.authorization = Authorization(message_refs=[*args.authorization.message_refs,current.id],quotes=args.authorization.quotes)
    result = runtime.services['user_memory'].write(args,ctx)
    assert result.error and result.error.code == 'NOT_AUTHORIZED', result.model_dump()


def test_sync_service_respects_tool_timeout(session_factory):
    from journeyplus.agent.tools.holdings import read
    from journeyplus.agent.tools.contracts import HoldingsReadInput
    runtime,store,w,ctx = context(session_factory)
    class SlowMemory:
        def read(self,args):
            time.sleep(.06)
            return []
    ctx.services['user_memory'] = SlowMemory()
    definition = ToolDefinition('holdings.read','Read',HoldingsReadInput,read,timeout_seconds=.01)
    result = asyncio.run(runtime.ports.registry.execute((definition,HoldingsReadInput(),'READ'),ctx))
    assert result.error and result.error.code == 'SOURCE_UNAVAILABLE', result.model_dump()


def test_parse_truncated_page_preserves_incomplete_coverage(session_factory):
    from journeyplus.agent.tools.research import parse
    _,store,w,ctx = context(session_factory)
    html = '<article><h1>From Example Gold to Other Platinum</h1><div class="instructions">My application was approved</div></article>'
    ref = store.artifacts.put(w['id'],'PAGE',{'raw_html':html,'final_url':'https://statusmatcher.com/report/12345','raw_truncated':True})
    result = asyncio.run(parse(ResearchInput(page_refs=[ref]),ctx))
    assert result.coverage['complete'] is False, result.model_dump()


def test_product_pages_survive_unavailable_agent_model(session_factory):
    from journeyplus.product.api import create_product_app
    from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
    from fastapi.testclient import TestClient
    class Unavailable(UnconfiguredModel):
        disabled = False
        async def initialize(self):
            raise RuntimeError('Simulated provider unavailable; no network attempted')
    app = create_product_app(session_factory,agent_model=Unavailable())
    with TestClient(app) as client:
        assert client.get('/holdings').status_code == 200


def test_saved_route_next_page_preserves_unresolved_scope(session_factory):
    from tests.test_knowledge_routes import edge
    from journeyplus.knowledge.models import MembershipTier
    from journeyplus.models import StatusHolding
    from journeyplus.agent.tools.routes import evaluate
    from journeyplus.agent.tools.contracts import RoutesInput
    runtime,store,w,ctx = context(session_factory)
    with session_factory.begin() as s:
        source,_ = edge(s,alternative=True)
        tier = s.get(MembershipTier,source)
        s.add(StatusHolding(program_key='resolved',tier_key='gold',program_display_name='Resolved',tier_display_name='Gold',program_id=tier.program_id,tier_id=source,identity_status='CONFIRMED'))
        s.add(StatusHolding(program_key='unresolved:other',tier_key='gold',program_display_name='Other',tier_display_name='Gold',identity_status='NEEDS_CONFIRMATION'))
    first = asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'saved'}},limit=1),ctx))
    assert first.data['unresolved_sources'] and first.next_cursor
    second = asyncio.run(evaluate(RoutesInput(operation='search',query_ref=first.data['query_ref'],cursor=first.next_cursor,limit=1),ctx))
    assert second.data.get('unresolved_sources') == first.data['unresolved_sources'], second.model_dump()
    assert second.coverage['complete'] is False


def test_waiting_replay_preserves_receipt_refs(session_factory):
    from tests.test_knowledge_routes import edge
    from journeyplus.agent.tools.contracts import WaitingInput
    runtime,store,w,ctx = context(session_factory)
    store.start(w['id'],'Create and update my waiting task','wait',0)
    auth={'message_refs':[store.load_context_index(w['id'])['messages'][0].id],'quotes':['Create and update my waiting task']}
    with session_factory.begin() as s:source,_=edge(s)
    query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}
    service=runtime.services['waiting']
    created=service.manage(WaitingInput(operation='create',query=query,authorization=auth,operation_key='new'),ctx)
    assert service.check()['status']=='RESULT_PENDING'
    listed=service.manage(WaitingInput(operation='list'),ctx).data['goals'][0]
    args=WaitingInput(operation='update',query=query,goal_ref=listed['ref'],expected_revision=listed['revision'],authorization=auth,operation_key='update')
    first=service.manage(args,ctx)
    second=service.manage(args,ctx)
    assert first.data == second.data, {'first_ref':first.data['before'].get('result_snapshot_ref'),'replayed_ref':second.data['before'].get('result_snapshot_ref')}


def test_update_to_existing_program_reports_conflict(session_factory):
    from journeyplus.agent.tools.contracts import HoldingsWriteInput
    runtime,store,w,r,ctx,args=setup(session_factory)
    memory=runtime.services['user_memory']
    first=memory.write(args,ctx)
    other=args.model_copy(update={'identity':args.identity.model_copy(update={'program_name':'Other'}),'operation_key':'other'})
    second=memory.write(other,ctx)
    update=HoldingsWriteInput(operation='update',holding_ref=second.data['after']['ref'],expected_revision=second.data['revision'],identity=args.identity,authorization=args.authorization,operation_key='merge')
    valid,error=runtime.ports.registry.validate('holdings.write',update.model_dump(mode='json',exclude_unset=True))
    assert not error
    result=asyncio.run(runtime.ports.registry.execute(valid,ctx))
    assert result.error and result.error.code=='CONFLICT', result.model_dump()
