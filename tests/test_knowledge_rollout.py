import pytest
from fastapi.testclient import TestClient
from journeyplus.product.api import create_product_app
from tests.db_fixture import factory


def test_unified_switch_moves_all_three_entries_without_changing_default(factory):
    legacy=TestClient(create_product_app(factory))
    assert legacy.get('/',follow_redirects=False).headers['location']=='/holdings'
    client=TestClient(create_product_app(factory,knowledge_read_mode='unified'))
    for before,after in [('/agent','/workspace'),('/matches','/explore'),('/briefs','/knowledge')]:
        response=client.get(before,follow_redirects=False)
        assert response.status_code==307 and response.headers['location']==after
    assert client.get('/v1/briefs').json()['code']=='LEGACY_CONSUMER_DISABLED'
    assert client.get('/v1/status-holdings').status_code==200
    assert client.get('/knowledge').status_code==200


def test_rollback_keeps_read_only_facts_and_fences_natural_confirmation(factory):
    client=TestClient(create_product_app(factory,knowledge_read_mode='rollback'))
    assert client.get('/knowledge').status_code==200
    response=client.post('/v1/status-holdings',json={})
    assert response.status_code==503 and response.json()['code']=='USER_WRITES_PAUSED'
    for path in ['/v2/agent/workspaces/unknown/messages','/v2/agent/workspaces/unknown/confirm','/v2/wait-goal/unknown/seen']:
        response=client.post(path,json={})
        assert response.status_code==410 and response.json()['code']=='AGENT_RUNTIME_RETIRED'
    assert client.post('/v2/explore/query',json={}).json()['code']=='RECOMMENDATIONS_PAUSED'
    assert client.get('/v2/rollout').json()['user_writes_paused'] is True
    assert client.get('/agent',follow_redirects=False).headers['location']=='/knowledge'


def test_invalid_read_mode_fails_before_serving(factory):
    with pytest.raises(ValueError,match='read mode'):create_product_app(factory,knowledge_read_mode='mixed')


def test_old_detail_link_preserves_identity_in_new_entry(factory):
    from uuid import uuid4
    identity=uuid4();client=TestClient(create_product_app(factory,knowledge_read_mode='unified'))
    response=client.get('/opportunities/'+str(identity),follow_redirects=False)
    assert response.headers['location']=='/knowledge?legacy_opportunity='+str(identity)
    assert client.get('/v2/legacy/opportunities/'+str(identity)).json()['status']=='NOT_FOUND'
