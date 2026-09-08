"""Replacement acceptance for retired v1/v2 execution, keeping history readable."""
from datetime import timedelta
from uuid import UUID,uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from journeyplus.models import AgentInteraction,StatusHolding,now_utc
from journeyplus.workspace_models import WorkspaceMessage
from journeyplus.product.api import create_product_app


def test_old_writes_retired_and_new_shell_never_initializes_workflow(session_factory):
    with TestClient(create_product_app(session_factory)) as client:
        for path in ['/v1/agent/turn','/v2/agent/workspaces',
                     '/v2/agent/workspaces/'+str(uuid4())+'/messages',
                     '/v2/agent/workspaces/'+str(uuid4())+'/confirm',
                     '/v2/agent/workspaces/'+str(uuid4())+'/deliveries',
                     '/v2/wait-goal/'+str(uuid4())+'/seen']:
            response=client.post(path,json={})
            assert response.status_code==410 and response.json()['code']=='AGENT_RUNTIME_RETIRED'
        assert 'workspace_v3.js' in client.get('/workspace').text
        assert client.get('/agent',follow_redirects=False).headers['location']=='/workspace'
        w=client.post('/v3/agent/workspaces',json={}).json()
        base='/v3/agent/workspaces/'+w['id']
        run=client.post(base+'/runs',json={'text':'hello','client_message_id':'one','expected_revision':0}).json()
        events=client.get(base+'/runs/'+run['run_id']+'/events').text
        assert 'MODEL_NOT_CONFIGURED' in events and 'partial' in events
        assert client.get('/knowledge').status_code==200
        assert client.get('/explore').status_code==200


def test_legacy_read_and_import_preserve_text_without_executing_pending(session_factory):
    with session_factory.begin() as session:
        row=AgentInteraction(status='ACTIVE',state={'pending_action':{'kind':'HOLDING_SAVE'},'task_context':{'intent':'ROUTES'}},
            provider='fixture',model='fixture',schema_version='workspace-1',prompt_version='workspace-1',expires_at=now_utc()+timedelta(hours=1))
        session.add(row);session.flush();identity=str(row.id)
        session.add(WorkspaceMessage(workspace_id=row.id,turn_id=uuid4(),role='USER',ordinal=1,content={'text':'保留旧对话原文'}))
    with TestClient(create_product_app(session_factory)) as client:
        old=client.get('/v2/agent/workspaces/'+identity).json()
        assert old['read_only'] and old['messages'][0]['text']=='保留旧对话原文'
        assert old['pending_action']['kind']=='HOLDING_SAVE'
        response=client.post('/v3/agent/workspaces',json={'import_workspace_id':identity})
        assert response.status_code==200
        current=client.get('/v3/agent/workspaces/'+response.json()['id']).json()
        assert '保留旧对话原文' in str(current['messages'])
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(StatusHolding))==0
            assert 'task_context' not in session.get(AgentInteraction,UUID(response.json()['id'])).state


def test_retired_execution_precedes_all_rollout_modes(session_factory):
    for mode in ('legacy','unified','rollback'):
        with TestClient(create_product_app(session_factory,knowledge_read_mode=mode)) as client:
            for path in ('/v1/agent/turn','/v2/agent/workspaces/x/messages','/v2/wait-goal/x/seen'):
                assert client.post(path,json={}).status_code==410
            assert client.get('/v1/agent/state').status_code==200


def test_disabled_network_never_probes_search_on_startup(session_factory,monkeypatch):
    from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
    from journeyplus.agent.composition import compose_business
    from journeyplus.product.agent_api import create_agent_app
    runtime,store=compose_business(session_factory,UnconfiguredModel(),network_enabled=False)
    probes=[]
    async def probe():probes.append('unexpected')
    monkeypatch.setattr(runtime.services['research'].search_backend,'initialize',probe)
    with TestClient(create_agent_app(runtime,store)) as client:
        assert client.get('/workspace').status_code==200
        assert client.post('/v1/agent/turn',json={}).status_code==410
    assert not probes
