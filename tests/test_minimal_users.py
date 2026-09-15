import asyncio
from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,update
from journeyplus.accounts import UserAccount,LoginSession,create_account
from journeyplus.user_scope import acting_as,OWNER_ID
import journeyplus.user_isolation
from journeyplus.models import StatusHolding,AgentInteraction,now_utc
from journeyplus.agent.adapters.models import Artifact,RunCheckpoint
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
from journeyplus.agent.composition import compose_business
from journeyplus.product.agent_api import create_agent_app
from journeyplus.agent.adapters.artifacts import aware
from journeyplus.agent.adapters.persistence import StoreError
from tests.test_harness_runtime import FakeModel,answer

PASSWORD='Testing-private-2026!'

@pytest.fixture
def users(session_factory):
    a=create_account(session_factory,'alice',PASSWORD,identity=OWNER_ID)
    b=create_account(session_factory,'bob',PASSWORD)
    return a,b

def holding(factory,uid,tier):
    with acting_as(uid),factory.begin() as s:
        row=WorkflowHolding(program_key='marriott bonvoy',tier_key=tier,program_display_name='Marriott Bonvoy',tier_display_name=tier)
        s.add(row);s.flush();return row.id

def test_holdings_scoped_for_both_mappings_and_column_queries(session_factory,users):
    a,b=users;ha=holding(session_factory,a,'Gold');hb=holding(session_factory,b,'Platinum')
    for uid,wanted,other in [(a,ha,hb),(b,hb,ha)]:
        with acting_as(uid),session_factory() as s:
            assert list(s.scalars(select(WorkflowHolding.id)))==[wanted]
            assert list(s.scalars(select(StatusHolding.id)))==[wanted]
            assert s.get(WorkflowHolding,other) is None
            assert s.get(StatusHolding,other) is None
    with acting_as(a),session_factory.begin() as s:
        s.execute(update(WorkflowHolding).where(WorkflowHolding.id==hb).values(tier_key='BAD'))
    with acting_as(b),session_factory() as s:assert s.get(WorkflowHolding,hb).tier_key=='Platinum'

def test_sliding_ttl_only_new_message_and_artifacts(session_factory,users):
    runtime,store=compose_business(session_factory,FakeModel([]))
    with acting_as(users[0]):
        w=store.current();ref=store.artifacts.put(w['id'],'MATERIAL',{'body':'keep'})
        with session_factory.begin() as s:
            expires=now_utc()+timedelta(hours=1)
            s.get(AgentInteraction,UUID(w['id'])).expires_at=expires
            s.get(Artifact,UUID(ref[9:])).expires_at=expires
        assert store.current()['id']==w['id']
        store.read(w['id'])
        with session_factory() as s:assert aware(s.get(AgentInteraction,UUID(w['id'])).expires_at)==aware(expires)
        started=store.start(w['id'],'hello','message',w['revision'])
        with session_factory() as s:
            renewed=aware(s.get(AgentInteraction,UUID(w['id'])).expires_at)
            assert renewed>now_utc()+timedelta(hours=23)
            assert aware(s.get(Artifact,UUID(ref[9:])).expires_at)==renewed
        assert store.start(w['id'],'hello','message',w['revision'])==started
        with session_factory() as s:assert aware(s.get(AgentInteraction,UUID(w['id'])).expires_at)==renewed
    asyncio.run(runtime.services['research'].close())

def test_http_ownership_new_session_and_logout(session_factory,users):
    runtime,store=compose_business(session_factory,FakeModel([answer()]))
    with TestClient(create_agent_app(runtime,store,initialize_model=False)) as client:
        assert client.get('/v3/agent/workspaces/current').status_code==401
        assert client.post('/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
        wa=client.get('/v3/agent/workspaces/current').json()
        with acting_as(users[0]):ref=store.artifacts.put(wa['id'],'MATERIAL',{'secret':'alice'})
        assert client.get('/v3/agent/workspaces/current').json()['id']==wa['id']
        assert client.post('/auth/logout').status_code==200
        assert client.get('/v3/agent/workspaces/'+wa['id']).status_code==401
        assert client.post('/auth/login',json={'username':'bob','password':PASSWORD}).status_code==200
        wb=client.get('/v3/agent/workspaces/current').json()
        assert wb['id']!=wa['id']
        assert client.get('/v3/agent/workspaces/'+wa['id']).status_code==404
        assert client.get(f"/v3/agent/workspaces/{wa['id']}/artifacts/{ref[9:]}").status_code==404
        assert client.get(f"/v3/agent/workspaces/{wb['id']}/artifacts/{ref[9:]}").status_code==404
        assert client.post('/v3/agent/workspaces',json={'import_workspace_id':wa['id']}).status_code==410
        assert client.post('/v3/agent/workspaces',json={},headers={'origin':'https://evil.example'}).status_code==403
        wc=client.post('/v3/agent/workspaces',json={}).json()
        assert wc['id']!=wb['id']
        assert client.get('/v3/agent/workspaces/'+wb['id']).status_code in (404,410)
        with acting_as(users[0]):assert store.read(wa['id'])['id']==wa['id']

def test_recovery_restores_user_scope(session_factory,users):
    from journeyplus.agent.tools.contracts import HoldingsReadInput
    from journeyplus.agent.harness.contracts import ToolDefinition,ToolResult
    holding(session_factory,users[0],'Gold');holding(session_factory,users[1],'Platinum')
    model=FakeModel([[{'type':'tool_call_ready','call_id':'read','name':'holdings.read','arguments':{}},{'type':'turn_end','finish_reason':'tool_calls'}],answer()])
    runtime,store=compose_business(session_factory,model)
    with acting_as(users[1]):
        w=store.current();r=store.start(w['id'],'my memberships','m',w['revision'])
    asyncio.run(runtime.run(r['run_id'])) # default owner scope, as in recovery
    results=[p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result']
    assert len(results[0]['data']['holdings'])==1
    assert results[0]['data']['holdings'][0]['tier_name']=='Platinum Elite'
    asyncio.run(runtime.services['research'].close())


def test_new_workspace_invalidates_running_effects_and_preserves_holdings(session_factory,users):
    from journeyplus.agent.harness.contracts import ExecutionContext
    from journeyplus.agent.harness.execution import active_call
    from journeyplus.agent.adapters.transactions import transaction
    from time import monotonic
    keep=holding(session_factory,users[0],'Gold')
    runtime,store=compose_business(session_factory,FakeModel([]))
    with acting_as(users[0]):
        old=store.current();r=store.start(old['id'],'save later','m',0)
        lease=str(uuid4());state=store.claim_run(r['run_id'],lease)
        new=store.current(fresh=True)
        assert new['replaced_runs']==[r['run_id']]
        with pytest.raises(StoreError):store.read(old['id'])
        ctx=ExecutionContext(old['id'],state['turn_id'],'late',str(users[0]),monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services,r['run_id'],lease)
        token=active_call.set(ctx)
        try:
            with pytest.raises(TimeoutError):
                with transaction(session_factory) as s:s.get(WorkflowHolding,keep).tier_key='BAD'
        finally:active_call.reset(token)
        store.cleanup()
        with session_factory() as s:
            assert s.get(AgentInteraction,UUID(old['id'])) is None
            assert s.get(WorkflowHolding,keep).tier_key=='Gold'
        assert store.current()['id']==new['id']
    asyncio.run(runtime.services['research'].close())


def test_expiry_rotates_only_the_idle_user(session_factory,users):
    runtime,store=compose_business(session_factory,FakeModel([]))
    with acting_as(users[0]):a=store.current()
    with acting_as(users[1]):b=store.current()
    with acting_as(users[0]),session_factory.begin() as s:s.get(AgentInteraction,UUID(a['id'])).expires_at=now_utc()-timedelta(seconds=1)
    with acting_as(users[0]):assert store.current()['id']!=a['id']
    with acting_as(users[1]):assert store.current()['id']==b['id']
    asyncio.run(runtime.services['research'].close())


def test_standalone_knowledge_login_lands_on_knowledge(session_factory,users):
    from journeyplus.product.knowledge_server import create_knowledge_app
    with TestClient(create_knowledge_app(session_factory)) as client:
        assert 'location.replace("/knowledge")' in client.get('/login').text
        assert client.get('/knowledge',follow_redirects=False).status_code==303
        assert client.post('/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
        assert client.get('/knowledge').status_code==200
