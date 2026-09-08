"""Opt-in real PostgreSQL transaction checks; refuse non-evaluation databases."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from time import monotonic
from uuid import UUID,uuid4
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from journeyplus.agent.composition import compose_business
from journeyplus.agent.adapters.models import OperationReceipt,RunCheckpoint
from journeyplus.agent.harness.contracts import ExecutionContext
from journeyplus.agent.tools.contracts import HoldingsWriteInput
from journeyplus.models import StatusHolding,UserBusinessOperation
from tests.test_harness_runtime import FakeModel


@pytest.fixture
def pg_factory():
    name=os.environ.get('JOURNEYPLUS_HARNESS_TEST_DATABASE')
    if not name:pytest.skip('Explicit isolated PostgreSQL database required')
    if not name.startswith('journeyplus_eval_'):pytest.fail('Refusing non-evaluation database')
    engine=create_engine(make_url(Settings.from_env().database_url).set(database=name))
    yield sessionmaker(engine,expire_on_commit=False)
    engine.dispose()


def test_postgres_competing_start_and_lease_are_exclusive(pg_factory):
    runtime,store=compose_business(pg_factory,FakeModel([]));w=store.create()
    def start(index):
        try:return store.start(w['id'],'hello',str(index),0)
        except ValueError as error:return str(error)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(start,[1,2]))
    accepted=[result for result in results if isinstance(result,dict)]
    assert len(accepted)==1 and 'RUN_ACTIVE' in results
    run=accepted[0]['run_id']
    owners=[str(uuid4()),str(uuid4())]
    with ThreadPoolExecutor(2) as pool:leases=list(pool.map(lambda owner:store.claim_run(run,owner),owners))
    assert sum(value is not None for value in leases)==1
    store.finish_run(run,owners[next(i for i,value in enumerate(leases) if value)],'CANCELED')


def test_postgres_atomic_effect_replay_and_crash_receipt(pg_factory):
    runtime,store=compose_business(pg_factory,FakeModel([]));w=store.create()
    program='事务验收'+uuid4().hex
    quote=f'请保存我的{program}金卡'
    run=store.start(w['id'],quote,'save',0)['run_id']
    message=store.load_context_index(w['id'])['messages'][0]
    with pg_factory() as s:
        turn=str(s.get(RunCheckpoint,UUID(run)).turn_id)
        before=s.scalar(select(func.count()).select_from(UserBusinessOperation))
    ctx=ExecutionContext(w['id'],turn,'effect','local-user',monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)
    args=HoldingsWriteInput(operation='create',identity={'program_name':program,'tier_name':'金卡'},operation_key='save',authorization={'message_refs':[message.id],'quotes':[quote]})
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:runtime.services['user_memory'].write(args,ctx),range(2)))
    assert results[0].data==results[1].data and not results[0].error
    with pg_factory() as s:
        assert s.scalar(select(func.count()).select_from(StatusHolding).where(StatusHolding.program_display_name==program))==1
        assert s.scalar(select(func.count()).select_from(UserBusinessOperation))==before+1
    assert store.completed_operations(run)==[results[0].data['operation_ref']]
    runtime.cancel(run);asyncio.run(runtime.run(run))
    assert store.read(w['id'])['operations'][0]['operation_ref']==results[0].data['operation_ref']


def test_postgres_jsonb_route_pagination_retains_snapshot_order(pg_factory):
    from journeyplus.agent.tools.routes import result_page
    runtime,store=compose_business(pg_factory,FakeModel([]));workspace=store.create()
    order=[str(number) for number in reversed(range(25))]
    payload={'route_order':order,'routes':{key:{'ref':key,'step_refs':[], 'from':'Source','to':'Target '+key,
              'cost':{'state':'UNKNOWN'},'material_caveats':['Condition '*100]} for key in order}}
    ref=store.artifacts.put(workspace['id'],'ROUTES',payload)
    first,cursor=result_page(payload,ref,0,4);seen=[row['ref'] for row in first]
    saved=store.artifacts.read(workspace['id'],ref)['payload']
    assert list(saved['routes'])!=order  # Exercise the real JSONB ordering change.
    while cursor:
        page,cursor=result_page(saved,ref,int(cursor.rsplit('|',1)[1]),4)
        seen.extend(row['ref'] for row in page)
    assert seen==[ref+'#route:'+key for key in order]


def test_postgres_resume_pending_write_after_committed_effect(pg_factory):
    from datetime import timedelta
    from journeyplus.models import now_utc
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    from tests.test_harness_runtime import answer
    runtime,store=compose_business(pg_factory,FakeModel([]));workspace=store.create()
    program='恢复验收'+uuid4().hex;quote=f'请保存我的{program}金卡'
    run=store.start(workspace['id'],quote,'save',0)['run_id'];owner=str(uuid4())
    state=store.claim_run(run,owner)
    message=store.load_context_index(workspace['id'])['messages'][0]
    args=HoldingsWriteInput(operation='create',identity={'program_name':program,'tier_name':'金卡'},
        operation_key='save',authorization={'message_refs':[message.id],'quotes':[quote]})
    call={'call_id':'pending-write','name':'holdings.write','arguments':args.model_dump(mode='json',exclude_unset=True)}
    store.append_message(run,owner,ModelMessage(role='assistant',content=[Part(type='tool_call',**call)]))
    store.save_checkpoint(run,owner,phase='TOOLS_PENDING',pending_calls=[call])
    store.tool_intent(run,owner,call,'USER_WRITE')
    ctx=ExecutionContext(workspace['id'],state['turn_id'],call['call_id'],'local-user',
        monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)
    committed=runtime.services['user_memory'].write(args,ctx)
    # Fault window: business COMMIT succeeded, tool result/checkpoint did not.
    assert committed.data['outcome']=='APPLIED'
    with pg_factory.begin() as session:
        session.get(RunCheckpoint,UUID(run)).heartbeat_at=now_utc()-timedelta(seconds=46)
    model=FakeModel([answer('已保存，操作回执已恢复。')])
    recovered,new_store=compose_business(pg_factory,model)
    asyncio.run(recovered.run(run))
    assert new_store.events(workspace['id'],run)[1]=='COMPLETED'
    results=[part.result for msg in model.inputs[0] for part in msg.content if part.type=='tool_result']
    assert len(results)==1 and results[0]['data']['operation_ref']==committed.data['operation_ref']
    with pg_factory() as session:
        assert session.scalar(select(func.count()).select_from(StatusHolding).where(StatusHolding.program_display_name==program))==1
        assert session.scalar(select(func.count()).select_from(OperationReceipt).where(OperationReceipt.entity_id==UUID(committed.data['after']['ref'].removeprefix('holding:'))))==1
    with pytest.raises(ValueError):store.tool_intent(run,owner,call,'USER_WRITE')
