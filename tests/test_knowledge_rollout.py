import pytest
from fastapi.testclient import TestClient
from journeyplus.product.api import create_product_app
from journeyplus.config import Settings
from tests.db_fixture import factory


@pytest.mark.parametrize('obsolete_mode', ['legacy','unified','rollback'])
def test_old_environment_cannot_switch_or_disable_current_consumers(factory, monkeypatch, obsolete_mode):
    monkeypatch.setenv('JOURNEYPLUS_KNOWLEDGE_READ_MODE', obsolete_mode)
    assert not hasattr(Settings.from_env(), 'knowledge_read_mode')
    client = TestClient(create_product_app(factory))
    assert client.get('/',follow_redirects=False).headers['location']=='/holdings'
    for path in ('/matches','/briefs','/knowledge','/explore','/workspace','/v1/briefs','/v1/personalized-matches'):
        assert client.get(path).status_code==200
    assert client.get('/v2/rollout').json()=={'mode':'aiworkflow','user_writes_paused':False,'recommendations_enabled':True}


def test_maintenance_only_pauses_user_writes_and_retired_execution_stays_retired(factory):
    client=TestClient(create_product_app(factory,knowledge_user_writes_paused=True))
    for path in ('/knowledge','/matches','/briefs','/v1/briefs'):
        assert client.get(path).status_code==200
    assert client.post('/v1/status-holdings',json={}).json()['code']=='USER_WRITES_PAUSED'
    for path in ('/v2/agent/workspaces/unknown/messages','/v2/wait-goal/unknown/seen'):
        assert client.post(path,json={}).status_code==410
    result=client.post('/v2/explore/query',json={})
    assert result.status_code==200
    assert client.get('/v2/rollout').json()['recommendations_enabled']
    assert factory.kw['info']['user_business_writes_paused']
    assert factory.kw['info']['user_business_journal'] is False
