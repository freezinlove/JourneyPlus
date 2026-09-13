"""Acceptance of architecture audit fixes using the selected original schema."""
import asyncio
import json
from datetime import datetime, date, timedelta, UTC
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from journeyplus.contracts import FactSet
from journeyplus.models import ArticleOpportunityRecord, StatusEvent, FactSetRecord, BriefRecord, AgentWaitGoal
from journeyplus.product.api import create_product_app
from journeyplus.product.knowledge_server import create_knowledge_app
from journeyplus.product.brief_data import fee_view, relation_context
from journeyplus.product.opportunities import PersonalizedMatchService, _fee_labels_for_target
from journeyplus.agent.adapters.workflow_knowledge import WorkflowUserData, WorkflowKnowledgePort
from journeyplus.knowledge.workflow_knowledge import identity_id, WorkflowActivityReader
from journeyplus.knowledge.workflow_routes import WorkflowRouteService
from journeyplus.knowledge.workflow_explore import explore
from journeyplus.knowledge.routes import RouteQuery
from journeyplus.memberships_validity import membership_date
from tests.test_agent_workflow_reads import original_factory, seed, context, call


def source_query(**kwargs):
    return RouteQuery(starting_tier_ids=[identity_id('tier','marriott bonvoy::platinum')], use_saved_holdings=False, **kwargs)


def test_expired_holdings_are_retained_but_excluded_by_all_consumers(original_factory, session_factory):
    identity = seed(original_factory)
    today = membership_date()
    with original_factory.begin() as s:
        s.execute(text("INSERT INTO status_holdings (id,program_key,tier_key,program_display_name,tier_display_name,valid_until,created_at,updated_at) VALUES (:id,'marriott bonvoy','platinum','Marriott Bonvoy','Platinum',:expiry,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),
                  {'id':uuid4().hex,'expiry':today-timedelta(days=1)})
    def inspect():
        with original_factory() as s:
            matches = PersonalizedMatchService(s).read()
            relation = relation_context(s).for_opportunity(identity)
            explored = explore(s, RouteQuery(use_saved_holdings=True))
            return matches, relation, explored, WorkflowUserData(original_factory).route_sources('saved')
    matches, relation, explored, sources = inspect()
    assert len(matches.holdings) == 1 and not matches.forest.roots
    assert relation.status == 'NO_ACTIVE_HOLDINGS' and sources and not explored['routes']
    # Internal source reads retain expired rows so Agent can explain exclusion.
    assert sources[0]['valid_until']==(today-timedelta(days=1)).isoformat()
    for expiry in (today, None):
        with original_factory.begin() as s:
            s.execute(text('UPDATE status_holdings SET valid_until=:expiry'), {'expiry':expiry})
        matches, relation, explored, sources = inspect()
        assert matches.forest.roots and relation.status == 'DIRECT' and explored['routes'] and sources
    assert membership_date(datetime(2026, 9, 13, 16, 30, tzinfo=UTC)) == date(2026, 9, 14)


@pytest.mark.parametrize('cost,expected,free', [
    (None,'FREE',True), ('','FREE',True), ('免费','FREE',True),
    ('USD 49','PAID',False), ('收费，金额未公布','PAID',False), ('费用待公布','UNKNOWN',False),
    ('免费；可选升级 USD 99','FREE',True),
    ('USD 49；可选升级 USD 99','PAID',False),
])
def test_shared_fees_in_brief_graph_page_and_real_agent_tools(original_factory, session_factory, cost, expected, free):
    identity = seed(original_factory)
    with original_factory.begin() as s:
        row = s.get(ArticleOpportunityRecord, identity)
        facts = json.loads(json.dumps(row.facts))
        facts['cost']['value'] = cost
        facts['application_routes'][0].update(cost=cost, prices=[])
        row.facts = facts
    with original_factory() as s:
        detail = PersonalizedMatchService(s).detail(identity, include_current_path=False)
        assert fee_view(detail.facts).status == expected
        page = WorkflowActivityReader(s).detail(identity)
        assert page['fee']['status'] == expected
        if free:
            assert any('免费' in label for label in _fee_labels_for_target(detail.facts, 'gold'))
    runtime, _, ctx = context(session_factory, original_factory)
    result = call(runtime, ctx, 'routes.evaluate', {'operation':'search','query':{
        'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]},
        'constraints':{'free_only':True}}})
    candidates = result.data['candidates']
    if free:
        assert candidates and all(c['cost']['is_proven_free'] for c in candidates)
        assert all(c['constraint_match']=='SATISFIES' for c in candidates)
    elif cost in {'USD 49', 'USD 49；可选升级 USD 99'}:
        assert not candidates
    else:
        assert candidates and not any(c['cost']['is_proven_free'] for c in candidates)


def history_fixture(factory):
    article_id = seed(factory)
    with factory.begin() as s:
        article = s.get(ArticleOpportunityRecord, article_id)
        event = StatusEvent(created_from_key=str(uuid4()), program='Audit Rewards', summary='History fixture')
        s.add(event); s.flush()
        rows = []
        for version in range(1,14):
            facts = json.loads(json.dumps(article.facts)); facts['event_id'] = str(event.id)
            facts['status_mappings'][0]['conditions'] = '仅限指定地区；此文字只作说明'
            facts['status_mappings'][0]['availability'] = 'CONDITIONAL'
            record = FactSetRecord(event_id=event.id, version=version, schema_version='5', facts=facts)
            s.add(record); s.flush(); rows.append(record.id)
            if version != 5:
                brief = BriefRecord(fact_set_id=record.id,version=1,schema_version='statusmatch-brief-1',content={
                    'schema_version':'statusmatch-brief-1','fact_set_id':str(record.id),'title':f'Audit Rewards 第 {version} 版','summary':f'第 {version} 版摘要', 'source_links':[]})
                s.add(brief); s.flush()
        event.current_fact_set_id = rows[-1]; event.current_brief_id = brief.id
        return event.id, rows


def test_history_pagination_status_and_version_links_work_in_both_deployments(original_factory):
    identity, versions = history_fixture(original_factory)
    clients = [TestClient(create_knowledge_app(original_factory)), TestClient(create_product_app(original_factory))]
    for client in clients:
        page = client.get(f'/v2/activities/{identity}/history').json()
        assert len(page['versions']) == 10 and page['has_more'] and page['next_before_version'] == 4
        older = client.get(f'/v2/activities/{identity}/history?before_version=4').json()
        rows = page['versions'] + older['versions']
        assert [r['version_no'] for r in rows] == list(range(13,0,-1))
        assert not older['has_more'] and older['next_before_version'] is None
        for row in rows:
            datetime.fromisoformat(row['created_at'])
            assert 'briefs' not in row  # Full brief text is still disclosed on demand.
            assert row['brief_status'] == ('MISSING' if row['version_no']==5 else 'READY')
            if row['brief_status']=='MISSING':
                assert row['brief_url'] is None
                continue
            params = parse_qs(urlsplit(row['brief_url']).query)
            assert params['version_ref'] == [row['version_ref']]
            assert client.get(row['brief_url']).status_code == 200
            response = client.get(f'/v2/activities/{identity}?version_ref={row["version_ref"]}')
            assert response.status_code == 200, response.text
            detail = response.json()
            assert detail['briefs'][0]['content']['title'] == f'Audit Rewards 第 {row["version_no"]} 版'
        detail = client.get(f'/v2/activities/{identity}').json()
        assert client.get(detail['brief_url']).status_code == 200
        assert detail['options'][-1]['mappings'][0]['conditions'] == '仅限指定地区；此文字只作说明'


def test_waiting_empty_knowledge_keeps_goal_then_recovers_without_model(original_factory, session_factory):
    from journeyplus.agent.composition import compose_business
    from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
    runtime, _ = compose_business(session_factory, UnconfiguredModel(), read_factory=original_factory)
    query = {'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}
    with session_factory.begin() as s:
        goal = AgentWaitGoal(status='ACTIVE', conditions_schema_version=3, query=query)
        s.add(goal); s.flush(); identity, revision = goal.id, goal.revision
    waiting = runtime.services['waiting']
    for _ in range(2):
        result = waiting.check()
        assert result['status']=='KNOWLEDGE_NOT_READY' and result['retryable']
        assert not result['coverage']['search_performed'] and result['model_calls']==0
        with session_factory() as s:
            row = s.get(AgentWaitGoal,identity)
            assert row.status=='ACTIVE' and row.revision==revision and row.query==query
    seed(original_factory)
    assert waiting.check()['status'] == 'RESULT_PENDING'


@pytest.mark.parametrize('budget',[12345,100000])
def test_lazy_model_initialization_preserves_configured_context_budget(session_factory, budget):
    from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
    from journeyplus.agent.adapters.lazy_model import LazyModel
    from journeyplus.agent.composition import compose_business
    from journeyplus.product.agent_lifecycle import AgentLifecycle
    class LocalModel(UnconfiguredModel):
        disabled = False
        config = SimpleNamespace(model='local-fixture',input_token_soft=90000,input_token_limit=120000,context_token_budget=budget)
        async def initialize(self): pass
    runtime, store = compose_business(session_factory, LazyModel(LocalModel))
    lifecycle = AgentLifecycle(runtime, store)
    asyncio.run(lifecycle.initialize())
    assert lifecycle.status == 'READY'
    assert runtime.budget_limits['context_tokens'] == budget
