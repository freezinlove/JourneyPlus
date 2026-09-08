"""Business exploration remains usable without any Agent runtime or AI provider."""
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from journeyplus.models import AgentInteraction,UserBusinessOperation
from journeyplus.product.knowledge_server import create_knowledge_app
from tests.test_knowledge_routes import edge


def test_explore_query_and_version_detail_do_not_create_agent_state(session_factory):
    with session_factory.begin() as s:source,target=edge(s,alternative=True)
    with TestClient(create_knowledge_app(session_factory)) as client:
        assert client.get('/explore').status_code==200
        result=client.post('/v2/explore/query',json={'starting_tier_ids':[str(source)],'use_saved_holdings':False})
        assert result.status_code==200
        snapshot=result.json();assert len(snapshot['routes'])>=2
        step=next(iter(snapshot['steps'].values()))
        detail=client.get('/v2/activities/'+step['activity_ref'],params={'version_ref':step['version_ref']})
        assert detail.json()['version_ref']==step['version_ref']
        assert client.post('/v3/agent/workspaces',json={}).status_code==404
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(AgentInteraction))==0
        assert s.scalar(select(func.count()).select_from(UserBusinessOperation))==0


def test_explorer_frontend_has_no_agent_workspace_dependency():
    from pathlib import Path
    source=(Path(__file__).parents[1]/'src/journeyplus/product/static/explore.js').read_text()
    assert '/agent/' not in source
    assert 'journeyplus-workspace-v2' not in source
    assert '/v2/explore/query' in source
