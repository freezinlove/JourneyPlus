"""Retained knowledge pages read only the chosen AIWorkflow schema."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from journeyplus.knowledge.workflow_knowledge import catalog
from journeyplus.knowledge.workflow_routes import WorkflowRouteService
from journeyplus.knowledge.routes import RouteQuery
from journeyplus.models import ArticleOpportunityRecord, StatusEvent, FactSetRecord, BriefRecord
from journeyplus.contracts import Brief
from journeyplus.product.api import create_product_app
from journeyplus.product.knowledge_server import create_knowledge_app
from tests.test_agent_workflow_reads import original_factory, seed


@pytest.fixture(params=['independent', 'product'])
def client(request, original_factory):
    create = create_knowledge_app if request.param == 'independent' else create_product_app
    # Product lifespan performs maintenance; these are read-only endpoint checks.
    return TestClient(create(original_factory))


def source_tier(client):
    result = client.get('/v2/membership/catalog', params={'text': 'Marriott Bonvoy Platinum'})
    assert result.status_code == 200
    return result.json()['programs'][0]['tiers'][0]['id']


def query(client, **changes):
    args = {'starting_tier_ids': [source_tier(client)], 'use_saved_holdings': False}
    args.update(changes)
    response = client.post('/v2/explore/query', json=args)
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_routes_and_version_details_share_agent_projection(client, original_factory):
    identity = seed(original_factory)
    original_factory.statements.clear()
    before = set(inspect(original_factory.kw['bind']).get_table_names())
    assert client.get('/explore').status_code == 200
    assert client.get('/knowledge').status_code == 200
    filters = client.get('/v2/membership/filters')
    assert filters.status_code == 200
    with original_factory() as s:
        programs, tiers, _ = catalog(s)
        assert filters.json()['alliances'] == sorted({p.alliance for p in programs if p.alliance})
        source = next(t for t in tiers if t.display_name == 'Platinum')
        agent = WorkflowRouteService(s).query(RouteQuery(starting_tier_ids=[source.id], use_saved_holdings=False))
    snapshot = query(client)
    assert snapshot['data_model'] == 'aiworkflow'
    assert {r['ref'] for r in snapshot['routes']} == {
        r['ref'] for r in agent['server_routes'].values() if r['classification'] in agent['presentation_classes']}
    assert snapshot['routes']
    step = next(iter(snapshot['steps'].values()))
    assert step['activity_ref'] == str(identity)
    assert step['fees'][0]['amount'] == '49'
    assert step['action_link'] == 'https://example.com/apply'
    detail = client.get('/v2/activities/' + step['activity_ref'], params={'version_ref': step['version_ref']})
    assert detail.status_code == 200
    assert detail.json()['data_model'] == 'aiworkflow'
    assert detail.json()['version_ref'] == step['version_ref']
    assert client.get('/v2/activities/' + str(identity), params={'version_ref': str(uuid4())}).status_code == 409
    assert client.get('/v2/legacy/opportunities/' + str(identity)).json()['activity_ref'] == str(identity)
    assert set(inspect(original_factory.kw['bind']).get_table_names()) == before
    sql = '\n'.join(original_factory.statements).lower()
    assert not any(t in sql for t in ('membership_programs', 'membership_aliases', 'application_options', 'knowledge_migration_links'))
    assert not any(s.lstrip().lower().startswith(('insert ', 'update ', 'delete ', 'create ', 'alter ')) for s in original_factory.statements)


def test_free_budget_and_category_filters_do_not_show_known_violations(client, original_factory):
    seed(original_factory)
    assert query(client)['routes']
    for constraints in ({'free_only': True}, {'max_amount': '48', 'currency': 'USD'}, {'category': 'AIRLINE'}):
        result = query(client, **constraints)
        assert result['routes'] == [] and result['steps'] == {}
    assert query(client, max_amount='49', currency='USD')['routes']
    assert query(client, alliance='nonexistent')['routes'] == []
    for constraints in ({'max_amount': '50'}, {'max_amount': '50', 'currency': 'USD', 'free_only': True}):
        response = client.post('/v2/explore/query', json=constraints)
        assert response.status_code == 409
    assert client.post('/v2/explore/query', json={'starting_tier_ids': [str(uuid4())]}).status_code == 409


def test_unknown_fees_stay_uncertain_under_free_filter(client, original_factory):
    identity = seed(original_factory)
    with original_factory.begin() as s:
        row = s.get(ArticleOpportunityRecord, identity)
        facts = json.loads(json.dumps(row.facts))
        facts['application_routes'][0]['region'] = 'Argentina and Chile'
        row.facts = facts
    result = query(client, free_only=True)
    assert result['routes'][0]['classification'] == 'UNKNOWN'
    assert result['routes'][0]['cost']['state'] == 'UNKNOWN'
    step = next(iter(result['steps'].values()))
    assert step['fees'] == []
    assert step['conditional_items'][0]['amount'] == '49'


def test_saved_expired_unknown_and_public_sources_are_honest(client, original_factory):
    seed(original_factory)
    public = client.post('/v2/explore/query', json={'use_saved_holdings': False}).json()
    assert public['routes'] == [] and public['coverage']['search_complete'] is False
    assert '公开申请' in public['coverage']['message']
    empty = client.post('/v2/explore/query', json={}).json()
    assert not empty['coverage']['search_performed']
    assert '已保存会籍' in empty['coverage']['message']
    with original_factory.begin() as s:
        for key, tier, until in [('marriott bonvoy', 'platinum', None), ('unknown', 'gold', None), ('expired', 'gold', '2000-01-01')]:
            s.execute(text('INSERT INTO status_holdings (id,program_key,tier_key,program_display_name,tier_display_name,valid_until,created_at,updated_at) VALUES (:id,:key,:tier,:key,:tier,:until,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),
                {'id': uuid4().hex, 'key': key, 'tier': tier, 'until': until})
    saved = client.post('/v2/explore/query', json={'use_saved_holdings': True}).json()
    assert saved['routes']
    assert saved['coverage']['unresolved_holding_count'] == 1
    assert saved['coverage']['search_complete'] is False
    assert query(client)['coverage']['unresolved_holding_count'] == 0
    with original_factory.begin() as s:
        s.execute(text("UPDATE status_holdings SET valid_until='2000-01-01' WHERE program_key='marriott bonvoy'"))
    expired = client.post('/v2/explore/query', json={'use_saved_holdings': True}).json()
    assert expired['routes'] == [] and not expired['coverage']['search_performed']


def test_cards_pagination_and_old_fact_links_keep_their_brief_version(client, original_factory):
    article = seed(original_factory)
    with original_factory.begin() as s:
        event = StatusEvent(created_from_key=str(uuid4()), program='Official Rewards', summary='summary')
        s.add(event); s.flush()
        facts = json.loads(json.dumps(s.get(ArticleOpportunityRecord, article).facts))
        facts['event_id'] = str(event.id)
        ids = []
        for version in (1, 2):
            record = FactSetRecord(event_id=event.id, version=version, schema_version='5', facts=facts)
            s.add(record); s.flush(); ids.append(record.id)
            content = Brief(fact_set_id=record.id, title=f'Brief {version}', title_fact_keys=['what_happened'],
                summary=f'Summary {version}', summary_fact_keys=['what_happened'])
            brief = BriefRecord(fact_set_id=record.id, version=1, schema_version='1', content=content.model_dump(mode='json'))
            s.add(brief); s.flush()
        event.current_fact_set_id, event.current_brief_id = record.id, brief.id
        event_id = event.id
    first = client.get('/v2/activities', params={'view': 'cards', 'limit': 1}).json()
    second = client.get('/v2/activities', params={'view': 'cards', 'limit': 1, 'offset': 1}).json()
    assert first['has_more'] and not second['has_more']
    assert first['activities'][0]['ref'] != second['activities'][0]['ref']
    assert 'facts' not in first['activities'][0] and 'options' not in first['activities'][0]
    resolved = client.get('/v2/legacy/opportunities/' + str(ids[0])).json()
    assert resolved['activity_ref'] == str(event_id) and resolved['version_ref'] == str(ids[0])
    detail = client.get('/v2/activities/' + resolved['activity_ref'], params={'version_ref': resolved['version_ref']}).json()
    assert detail['name'] == 'Brief 1' and detail['is_current'] is False
    assert detail['briefs'][0]['content']['summary'] == 'Summary 1'
    history = client.get('/v2/activities/' + str(event_id) + '/history', params={'limit': 1}).json()
    assert history['has_more'] and history['versions'][0]['version_ref'] == str(ids[1])
    older = client.get('/v2/activities/' + str(event_id) + '/history', params={'limit': 1, 'before_version': 2}).json()
    assert not older['has_more'] and older['versions'][0]['version_ref'] == str(ids[0])


def test_duplicate_routes_are_removed(client):
    assert client.get('/v2/catalog?q=Flying').status_code == 404
    assert client.post('/v2/routes/query', json={}).status_code == 404
    paths = client.get('/openapi.json').json()['paths']
    assert '/v2/catalog' not in paths and '/v2/routes/query' not in paths


def test_explorer_frontend_has_no_agent_workspace_dependency():
    from pathlib import Path
    source = (Path(__file__).parents[1] / 'src/journeyplus/product/static/explore.js').read_text()
    assert '/agent/' not in source and 'journeyplus-workspace-v2' not in source
    assert '/v2/explore/query' in source


def test_independent_service_does_not_import_agent_runtime():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        "import sys; from journeyplus.product.knowledge_server import create_knowledge_app; "
        "create_knowledge_app(None); "
        "assert not any(m.startswith('journeyplus.agent.') for m in sys.modules)"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
