"""Execution evidence comes from real transactions, not model behavior."""
import asyncio
import time
from dataclasses import replace
from uuid import UUID,uuid4
from sqlalchemy import select,func,text
from journeyplus.agent.harness.execution import blocking_tool
from journeyplus.agent.harness.contracts import ToolDefinition,ToolResult
from journeyplus.agent.adapters.transactions import transaction
from journeyplus.agent.adapters.models import Artifact,RunCheckpoint
from tests.test_harness_tools import context
from tests.test_harness_runtime import Echo
from tests.test_harness_postgres import pg_factory


def test_thread_work_does_not_block_loop_and_timeout_cannot_commit(session_factory):
    runtime,store,w,ctx=context(session_factory)
    @blocking_tool
    def slow(args,ctx):
        time.sleep(.08)
        ref=ctx.artifact_port.put(ctx.workspace_id,'MATERIAL',{'late':True})
        return ToolResult(artifact_refs=[ref])
    definition=ToolDefinition('slow','Slow',Echo,slow,timeout_seconds=.03)
    async def exercise():
        ticks=[]
        async def ticker():
            for _ in range(6):
                await asyncio.sleep(.01);ticks.append(time.monotonic())
        task=asyncio.create_task(ticker())
        result=await runtime.ports.registry.execute((definition,Echo(value='x'),'READ'),ctx)
        await task
        return result,ticks
    result,ticks=asyncio.run(exercise())
    assert result.error.code=='SOURCE_UNAVAILABLE' and len(ticks)==6
    assert ticks[-1]-ticks[0]<.08
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Artifact))==0


def claimed(factory):
    runtime,store,w,ctx=context(factory)
    run=store.start(w['id'],'Exercise local execution','one',0)['run_id'];owner=str(uuid4())
    state=store.claim_run(run,owner)
    return runtime,store,w,replace(ctx,turn_id=state['turn_id'],run_id=run,lease_owner=owner)


def test_postgres_statement_deadline_rolls_back_artifact(pg_factory):
    runtime,store,w,ctx=claimed(pg_factory)
    @blocking_tool
    def slow(args,ctx):
        with transaction(pg_factory) as session:
            store.artifacts.put_in(session,ctx.workspace_id,'MATERIAL',{'uncommitted':True})
            session.execute(text('SELECT pg_sleep(0.3)'))
        return ToolResult()
    definition=ToolDefinition('slow','Slow',Echo,slow,timeout_seconds=.08)
    started=time.monotonic()
    result=asyncio.run(runtime.ports.registry.execute((definition,Echo(value='x'),'WORKSPACE_WRITE'),ctx))
    assert result.error.code=='SOURCE_UNAVAILABLE' and time.monotonic()-started<.25
    with pg_factory() as session:
        assert session.scalar(select(func.count()).select_from(Artifact).where(Artifact.workspace_id==UUID(w['id'])))==0


def test_postgres_displaced_owner_cannot_commit_tool_effect(pg_factory):
    runtime,store,w,ctx=claimed(pg_factory)
    with pg_factory.begin() as session:session.get(RunCheckpoint,UUID(ctx.run_id)).lease_owner=uuid4()
    @blocking_tool
    def write(args,ctx):
        ref=store.artifacts.put(ctx.workspace_id,'MATERIAL',{'must_not_exist':True})
        return ToolResult(artifact_refs=[ref])
    definition=ToolDefinition('write','Write',Echo,write)
    result=asyncio.run(runtime.ports.registry.execute((definition,Echo(value='x'),'WORKSPACE_WRITE'),ctx))
    assert result.error.code=='SOURCE_UNAVAILABLE'
    with pg_factory() as session:
        assert session.scalar(select(func.count()).select_from(Artifact).where(Artifact.workspace_id==UUID(w['id'])))==0


def test_postgres_lock_wait_obeys_tool_deadline(pg_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    runtime,store,w,ctx=claimed(pg_factory)
    locked=Event();release=Event()
    def holder():
        with pg_factory.begin() as session:
            session.execute(text('SELECT pg_advisory_xact_lock(748293099)'))
            locked.set();release.wait(2)
    @blocking_tool
    def blocked(args,ctx):
        with transaction(pg_factory) as session:
            session.execute(text('SELECT pg_advisory_xact_lock(748293099)'))
        return ToolResult()
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(holder);assert locked.wait(1)
        try:
            definition=ToolDefinition('blocked','Blocked',Echo,blocked,timeout_seconds=.08)
            start=time.monotonic()
            result=asyncio.run(runtime.ports.registry.execute((definition,Echo(value='x'),'READ'),ctx))
            assert result.error.code=='SOURCE_UNAVAILABLE' and time.monotonic()-start<.25
        finally:release.set();future.result()


def test_postgres_real_restricted_knowledge_role_can_query_without_user_access(pg_factory):
    from sqlalchemy import create_engine,event
    from sqlalchemy.orm import sessionmaker
    from journeyplus.agent.composition import compose_business
    from journeyplus.agent.tools.routes import evaluate
    from journeyplus.agent.tools.contracts import RoutesInput
    from tests.test_harness_runtime import FakeModel
    role='journeyplus_eval_knowledge_20260909'
    engine=pg_factory.kw['bind'];quote=engine.dialect.identifier_preparer.quote
    with engine.begin() as connection:
        if not connection.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}):
            connection.execute(text('CREATE ROLE '+quote(role)+' NOLOGIN'))
        tables=list(connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")))
        formal=[name for name in tables if not name.startswith('agent_') and name not in {'status_holdings','user_business_operations','alembic_version'}]
        connection.execute(text('GRANT USAGE ON SCHEMA public TO '+quote(role)))
        connection.execute(text('GRANT SELECT ON '+','.join(quote(name) for name in formal)+' TO '+quote(role)))
    restricted=create_engine(engine.url)
    @event.listens_for(restricted,'connect')
    def assume_role(connection,record):
        with connection.cursor() as cursor:cursor.execute('SET ROLE '+quote(role))
        connection.commit()
    read_factory=sessionmaker(restricted,expire_on_commit=False)
    try:
        with read_factory() as session:
            assert not session.scalar(text("SELECT has_table_privilege(current_user,'status_holdings','SELECT')"))
            assert not session.scalar(text("SELECT has_table_privilege(current_user,'agent_wait_goals','SELECT')"))
        runtime,store=compose_business(pg_factory,FakeModel([]),read_factory=read_factory)
        _,_,_,ctx=context(pg_factory);w=store.create()
        ctx=replace(ctx,workspace_id=w['id'],services=runtime.services,artifact_port=store.artifacts)
        result=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'none'}},limit=1),ctx))
        assert result.status in {'OK','EMPTY','PARTIAL'}
    finally:restricted.dispose()


def test_timeout_after_commit_reports_durable_success_not_failed_write(session_factory):
    from tests.test_harness_memory import setup
    runtime,store,w,run,ctx,args=setup(session_factory)
    @blocking_tool
    def committed_then_slow(arguments,context):
        result=context.services['user_memory'].write(arguments,context)
        assert result.data['outcome']=='APPLIED'
        time.sleep(.09)
        return result
    from journeyplus.agent.tools.contracts import HoldingsWriteInput
    definition=ToolDefinition('write','Write',HoldingsWriteInput,committed_then_slow,
                              effect='USER_WRITE',timeout_seconds=.05)
    result=asyncio.run(runtime.ports.registry.execute((definition,args,'USER_WRITE'),ctx))
    assert result.status=='PARTIAL' and result.error is None
    assert result.data['outcome']=='APPLIED' and result.data['operation_ref'].startswith('operation:')


def test_cancellation_while_claim_is_in_flight_cleans_owned_run(session_factory,monkeypatch):
    from journeyplus.agent.composition import compose
    from tests.test_harness_runtime import FakeModel
    model=FakeModel([]);runtime,store=compose(session_factory,model)
    w=store.create();run=store.start(w['id'],'cancel before model','one',0)['run_id']
    claim=store.claim_run
    from threading import Event
    started=Event()
    def slow_claim(*args):
        state=claim(*args);started.set();time.sleep(.06);return state
    monkeypatch.setattr(store,'claim_run',slow_claim)
    async def scenario():
        task=asyncio.create_task(runtime.run(run))
        while not started.is_set():await asyncio.sleep(.001)
        await runtime.cancel(run);await task
    asyncio.run(scenario())
    assert store.events(w['id'],run)[1]=='CANCELED' and model.inputs==[]
    assert run not in runtime.running_tasks and run not in runtime.cancellations


def test_postgres_cancel_open_transaction_rolls_back_and_releases_lease(pg_factory):
    from threading import Event
    from journeyplus.agent.composition import compose
    from tests.test_harness_runtime import FakeModel,call
    entered=Event();release=Event()
    @blocking_tool
    def write(args,ctx):
        with transaction(pg_factory) as session:
            ctx.artifact_port.put_in(session,ctx.workspace_id,'MATERIAL',{'must_rollback':True})
            entered.set();release.wait(2)
        return ToolResult()
    model=FakeModel([call(name='write')]);runtime,store=compose(pg_factory,model,[ToolDefinition('write','Write',Echo,write,effect='WORKSPACE_WRITE')])
    w=store.create();run=store.start(w['id'],'cancel write','one',0)['run_id']
    async def scenario():
        task=asyncio.create_task(runtime.run(run))
        while not entered.is_set():await asyncio.sleep(.001)
        cancel=asyncio.create_task(runtime.cancel(run))
        await asyncio.sleep(.01);release.set()
        await cancel;await task
    asyncio.run(scenario())
    assert store.events(w['id'],run)[1]=='CANCELED'
    with pg_factory() as session:
        assert not any(row.payload.get('must_rollback') for row in session.scalars(select(Artifact).where(Artifact.workspace_id==UUID(w['id']))))
        # The owner remains as audit metadata; terminal phase revokes authority.
        assert session.get(RunCheckpoint,UUID(run)).phase=='CANCELED'
    assert store.claim_run(run,str(uuid4())) is None
    assert run not in runtime.running_tasks


def test_postgres_history_search_preserves_unicode_casefold_and_scope(pg_factory):
    runtime,store,w,ctx=context(pg_factory)
    own=store.artifacts.put(w['id'],'MATERIAL',{'text':'Straße'})
    other=store.create();store.artifacts.put(other['id'],'MATERIAL',{'text':'STRASSE'})
    result=store.artifacts.search(w['id'],query='strasse')
    assert [row['ref'] for row in result['artifacts']]==[own]
    assert store.artifacts.search(w['id'],query='不存在')['artifacts']==[]
