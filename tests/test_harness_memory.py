import asyncio
from dataclasses import replace
from datetime import timedelta
from time import monotonic
from uuid import UUID
import pytest
from sqlalchemy import select
from journeyplus.models import AgentInteraction,StatusHolding,UserBusinessOperation,now_utc
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.composition import compose_business
from journeyplus.knowledge.access import KnowledgePort
from journeyplus.agent.harness.contracts import ExecutionContext
from journeyplus.agent.tools.contracts import HoldingsWriteInput
from tests.test_harness_runtime import FakeModel


def setup(factory):
    runtime,store=compose_business(factory,FakeModel([]),knowledge_port=KnowledgePort(factory))
    w=store.create();r=store.start(w['id'],'请保存我的测试俱乐部金卡。','save',0)
    message=store.load_context_index(w['id'])['messages'][0]
    context=ExecutionContext(w['id'],message.metadata['turn_id'],'call','local-user',monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)
    args=HoldingsWriteInput(operation='create',identity={'program_name':'测试俱乐部','tier_name':'金卡'})
    return runtime,store,w,r,context,args


def test_authorized_unresolved_save_receipt_journal_and_replay(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    memory=runtime.services['user_memory']
    first=memory.write(args,ctx);second=memory.write(args,ctx)
    assert first.data==second.data and first.data['outcome']=='APPLIED'
    assert first.data['after']['identity_status']=='NEEDS_CONFIRMATION'
    third=memory.write(args,replace(ctx,call_id="duplicate"))
    assert third.data['outcome']=='NOOP'
    with session_factory() as s:
        assert len(list(s.scalars(select(StatusHolding))))==1
        assert len(list(s.scalars(select(UserBusinessOperation))))==1
        assert len(list(s.scalars(select(OperationReceipt))))==2


def test_missing_current_turn_zero_write(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    result=runtime.services['user_memory'].write(args,replace(ctx,turn_id=str(__import__('uuid').uuid4())))
    assert result.error.code=='NOT_AUTHORIZED'
    with session_factory() as s:assert not list(s.scalars(select(StatusHolding)))


def test_revision_conflict_and_changed_idempotency_payload(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    memory=runtime.services['user_memory'];first=memory.write(args,ctx)
    conflicting=args.model_copy(update={'valid_until':'2027-01-01'})
    assert memory.write(conflicting,ctx).error.code=='CONFLICT'
    update=HoldingsWriteInput(operation='delete',holding_ref=first.data['after']['ref'],expected_revision=999)
    assert memory.write(update,replace(ctx,call_id="stale-delete")).error.code=='CONFLICT'


def test_workspace_expiry_preserves_operation_receipt(session_factory):
    runtime,store,w,r,ctx,args=setup(session_factory)
    runtime.services['user_memory'].write(args,ctx)
    with session_factory.begin() as s:s.get(AgentInteraction,UUID(w['id'])).expires_at=now_utc()-timedelta(seconds=1)
    assert store.cleanup()==1
    with session_factory() as s:
        assert len(list(s.scalars(select(OperationReceipt))))==1
        assert len(list(s.scalars(select(StatusHolding))))==1


def test_import_preserves_history_but_never_imports_execution_flags(session_factory):
    from uuid import uuid4
    from journeyplus.workspace_models import WorkspaceMessage
    runtime,store=compose_business(session_factory,FakeModel([]),knowledge_port=KnowledgePort(session_factory))
    original_text='请保存我的旧俱乐部金卡'
    with session_factory.begin() as s:
        legacy=AgentInteraction(status='ACTIVE',provider='old',model='old',prompt_version='old',schema_version='workspace-1',expires_at=now_utc()+timedelta(hours=1),state={'last_query':{'target':'locked'},'task_context':{'intent':'SAVE'},'references':{'K1':'old-route'},'pending_action':{'kind':'HOLDING_SAVE','program_name':'旧俱乐部'}})
        s.add(legacy);s.flush();old_id=str(legacy.id);turn=uuid4()
        s.add(WorkspaceMessage(workspace_id=legacy.id,turn_id=turn,ordinal=1,role='USER',content={'text':original_text}))
        s.add(WorkspaceMessage(workspace_id=legacy.id,turn_id=turn,ordinal=2,role='ASSISTANT',content={'text':'历史展示','blocks':[{'type':'route_graph','payload':{'routes':[{'ref':'K1','step_refs':[]}],'steps':{}}}]}))
    w=store.import_workspace(old_id);history=store.load_context_index(w['id'])
    assert 'last_query' not in history['state'] and 'task_context' not in history['state'] and 'pending_action' not in history['state']
    imported=history['messages'];assert imported[0].content[0].text==original_text
    ref=imported[1].content[1].ref
    assert store.artifacts.read(w['id'],ref)['payload']['blocks'][0]['payload']['routes'][0]['ref']=='old-route'
    ctx=ExecutionContext(w['id'],str(uuid4()),'new-call','local-user',monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)
    args=HoldingsWriteInput(operation='create',identity={'program_name':'旧俱乐部','tier_name':'金卡'})
    assert runtime.services['user_memory'].write(args,ctx).error.code=='NOT_AUTHORIZED'
    with session_factory() as s:assert not list(s.scalars(select(StatusHolding)))


def test_history_and_artifact_cursors_bind_query_workspace_and_snapshot(session_factory):
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    runtime,store=compose_business(session_factory,FakeModel([]),knowledge_port=KnowledgePort(session_factory))
    w=store.create();r=store.start(w['id'],'needle start','one',0)
    owner=str(__import__('uuid').uuid4());store.claim_run(r['run_id'],owner)
    for number in range(3):
        store.append_message(r['run_id'],owner,ModelMessage(role='assistant',content=[Part(type='text',text=f'needle {number}')]))
    first=store.history(w['id'],query='needle',limit=1)
    store.append_message(r['run_id'],owner,ModelMessage(role='assistant',content=[Part(type='text',text='needle later')]))
    second=store.history(w['id'],query='needle',cursor=first['next_cursor'],limit=10)
    assert second['total']==4 and len(second['messages'])==3
    with pytest.raises(ValueError):store.history(w['id'],query='changed',cursor=first['next_cursor'])
    for number in range(3):store.artifacts.put(w['id'],'MATERIAL',{'number':number})
    first=store.artifacts.search(w['id'],limit=1)
    later=store.artifacts.put(w['id'],'MATERIAL',{'number':'later'})
    second=store.artifacts.search(w['id'],cursor=first['next_cursor'],limit=10)
    assert second['total']==3 and all(item['ref']!=later for item in second['artifacts'])
    other=store.create()
    with pytest.raises(ValueError):store.artifacts.search(other['id'],cursor=first['next_cursor'])
    with pytest.raises(ValueError):store.artifacts.search(w['id'],cursor='invalid')
