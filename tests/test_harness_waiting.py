import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID
from sqlalchemy import select
from journeyplus.agent.tools.contracts import WaitingInput
from journeyplus.models import AgentInteraction,AgentWaitGoal,now_utc
from journeyplus.agent.adapters.models import OperationReceipt
from tests.test_agent_workflow_reads import context as workflow_context
from tests.test_candidate_routes import _mapping_opportunity
from journeyplus.knowledge.workflow_knowledge import identity_id


def context(factory):
    runtime,store,ctx=workflow_context(factory,factory)
    return runtime,store,store.read(ctx.workspace_id),ctx


def edge(session):
    _mapping_opportunity(session,slug='waiting-fixture',source_program='Marriott Bonvoy',
        source_tier='Platinum',target_program='Example Rewards',target_tier='Gold',amount=49,challenge=None)
    return identity_id('tier','marriott bonvoy::platinum'),identity_id('tier','example rewards::gold')


def test_waiting_is_explicit_durable_and_checks_without_model(session_factory):
    runtime,store,w,ctx=context(session_factory)
    quote='请按本次起点创建等待任务'
    store.start(w['id'],quote,'create-wait',0)
    ctx.turn_id=store.load_context_index(w['id'])['messages'][-1].metadata['turn_id']
    message=store.load_context_index(w['id'])['messages'][0]
    with session_factory.begin() as s:source,target=edge(s)
    args=WaitingInput(operation='create',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}})
    service=runtime.services['waiting'];created=service.manage(args,ctx)
    assert created.data['outcome']=='APPLIED'
    assert service.manage(args,ctx).data==created.data
    duplicate=service.manage(args,replace(ctx,call_id="duplicate"))
    assert duplicate.data["outcome"]=="NOOP"
    checked=service.check();assert checked['status']=='RESULT_PENDING' and checked['model_calls']==0
    listed=service.manage(WaitingInput(operation='list'),ctx)
    assert listed.data['goals'][0]['route_refs']
    ref=listed.data['goals'][0]['route_refs'][0]
    assert store.artifacts.read(w['id'],ref)['kind']=='ROUTES'
    with session_factory.begin() as s:s.get(AgentInteraction,UUID(w['id'])).expires_at=now_utc()-timedelta(seconds=1)
    store.cleanup()
    with session_factory() as s:
        assert len(list(s.scalars(select(AgentWaitGoal))))==1
        assert len(list(s.scalars(select(OperationReceipt))))==2
    assert not runtime.ports.model.inputs


def test_reactivating_old_goal_cannot_create_two_active_goals(session_factory):
    runtime,store,w,ctx=context(session_factory)
    quote='创建等待，取消后创建新的，再修改旧等待'
    store.start(w['id'],quote,'wait-conflict',0)
    ctx.turn_id=store.load_context_index(w['id'])['messages'][-1].metadata['turn_id']
    message=store.load_context_index(w['id'])['messages'][0]
    query={'sources':{'mode':'none'}}
    service=runtime.services['waiting']
    first=service.manage(WaitingInput(operation='create',query=query),ctx)
    ref=first.data['after']['ref'];revision=first.data['revision']
    canceled=service.manage(WaitingInput(operation='cancel',goal_ref=ref,expected_revision=revision),replace(ctx,call_id='cancel'))
    second=service.manage(WaitingInput(operation='create',query=query),replace(ctx,call_id='create-again'))
    result=service.manage(WaitingInput(operation='update',goal_ref=ref,expected_revision=canceled.data['revision'],
        query=query),replace(ctx,call_id='update'))
    assert result.error.code=='CONFLICT'
    assert result.data['existing']['ref']==second.data['after']['ref']
    with session_factory() as s:
        assert s.get(AgentWaitGoal,UUID(ref.removeprefix('goal:'))).status=='CANCELLED'
        assert len(list(s.scalars(select(AgentWaitGoal).where(AgentWaitGoal.status=='ACTIVE'))))==1
        assert len(list(s.scalars(select(OperationReceipt))))==3


def test_waiting_update_projects_old_evidence_and_clears_stale_state(session_factory):
    runtime,store,w,ctx=context(session_factory)
    quote='创建等待，并允许修改及取消本测试等待'
    store.start(w['id'],quote,'wait-lifecycle',0)
    ctx.turn_id=store.load_context_index(w['id'])['messages'][-1].metadata['turn_id']
    with session_factory.begin() as s:source,target=edge(s)
    query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}
    service=runtime.services['waiting']
    created=service.manage(WaitingInput(operation='create',query=query),ctx)
    assert service.check()['status']=='RESULT_PENDING'
    listed=service.manage(WaitingInput(operation='list'),ctx)
    goal=listed.data['goals'][0]
    payload=store.artifacts.read(w['id'],goal['result_snapshot_ref'])['payload']
    assert set(payload['steps'])=={sid for r in payload['routes'].values() for sid in r['step_refs']}
    assert store.artifacts.read(w['id'],payload['query_ref'])['payload']==goal['query']
    updated=service.manage(WaitingInput(operation='update',goal_ref=goal['ref'],expected_revision=goal['revision'],
        query=query),replace(ctx,call_id='update'))
    assert 'pending_result' not in updated.data['before']
    assert updated.data['before']['result_snapshot_ref']
    assert updated.data['after']['result_ref'] is None
    with session_factory() as s:
        row=s.get(AgentWaitGoal,UUID(goal['ref'][5:]))
        assert row.pending_result is None and row.last_candidate_signature is None and row.ended_at is None
    # Resetting the query explicitly allows a new check; old fingerprint cannot suppress it.
    assert service.check()['status']=='RESULT_PENDING'


def test_waiting_pages_are_complete_and_mutation_invalidates_cursor(session_factory):
    import pytest
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        rows=[AgentWaitGoal(status='CANCELLED',conditions_schema_version=3,query={'sources':{'mode':'none'}}) for _ in range(3)]
        s.add_all(rows);s.flush();first=rows[0].id
    service=runtime.services['waiting']
    page1=service.manage(WaitingInput(operation='list',limit=2),ctx)
    assert page1.status=='PARTIAL' and page1.coverage['total']==3 and len(page1.data['goals'])==2
    page2=service.manage(WaitingInput(operation='list',limit=2,cursor=page1.next_cursor),ctx)
    assert page2.coverage['complete'] and len(page2.data['goals'])==1
    with session_factory.begin() as s:s.get(AgentWaitGoal,first).revision+=1
    with pytest.raises(ValueError,match='STALE_REFERENCE'):
        service.manage(WaitingInput(operation='list',cursor=page1.next_cursor),ctx)


def test_legacy_pending_result_is_readable_without_new_route_semantics(session_factory):
    runtime,store,w,ctx=context(session_factory)
    legacy={'routes':[{'old_id':'old-format'}],'pending_action':{'kind':'SAVE'}}
    with session_factory.begin() as s:
        s.add(AgentWaitGoal(status='CANCELLED',conditions_schema_version=1,query={'old_scope':'x'},pending_result=legacy))
    result=runtime.services['waiting'].manage(WaitingInput(operation='list'),ctx)
    goal=result.data['goals'][0]
    assert goal['result_scope']=='LEGACY_READ_ONLY'
    assert store.artifacts.read(w['id'],goal['legacy_result_ref'])['payload']=={'pending_result':legacy}
    assert not goal.get('route_refs')
