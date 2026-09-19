"""Prices and graph nodes must identify the same tier within a target program."""
from uuid import uuid4
from copy import deepcopy

import pytest

from journeyplus.contracts import ApplicationRoute, FactField, FactSet, RoutePrice
from journeyplus.fee_policy import route_fees
from journeyplus.knowledge.workflow_routes import matching_paid, WorkflowRouteService, matching_forest
from journeyplus.knowledge.workflow_knowledge import graph_state, identity_id
from journeyplus.knowledge.simple_matching import MatchingQuery
from journeyplus.membership.normalization import program_tier_key
from journeyplus.product.opportunities import PersonalizedMatchService, _fee_labels_for_target
from tests.test_candidate_routes import _mapping_opportunity


@pytest.mark.parametrize('program,price_tier,graph_tier', [
    ('Asante Rewards', 'Asante Rewards Gold Elite Plus', 'Gold Elite Plus'),
    ('Royal Jordanian Royal Club', 'Royal Jordanian Royal Club Gold Sparrow', 'Gold Sparrow'),
    ('Flying Blue', 'Gold', 'Flying Blue GOLD'),
    ('Example Rewards', 'EXAMPLE REWARDS   Gold status', 'gold'),
])
def test_fee_identity_is_bidirectional_and_shared_by_labels(program, price_tier, graph_tier):
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value='match'),
        application_routes=[ApplicationRoute(scope='application', prices=[
            RoutePrice(target_tier=price_tier, amount=149, currency='USD', availability='AVAILABLE')])])
    before = facts.model_dump(mode='json')
    aliases = {program}
    assert program_tier_key(price_tier, aliases) == program_tier_key(graph_tier, aliases)
    policy = route_fees(facts, facts.application_routes[0], target_tier=graph_tier, program_aliases=aliases)
    assert policy.states == ['PAID'] and len(policy.prices) == 1
    assert matching_paid(facts, graph_tier, program_aliases=aliases)
    assert any('149' in label for label in _fee_labels_for_target(facts, graph_tier, program_aliases=aliases))
    assert facts.model_dump(mode='json') == before


@pytest.mark.parametrize('tier,amount,availability,paid', [
    ('Example Rewards Gold', 99, 'AVAILABLE', True),
    ('Example Rewards Silver', 99, 'AVAILABLE', None),
    ('Another Rewards Gold', 99, 'AVAILABLE', None),
    ('Example Rewards Gold Plus', 99, 'AVAILABLE', None),
    ('Example Rewards Gold', 99, 'CONDITIONAL', None),
    ('Example Rewards Gold', None, 'UNAVAILABLE', None),
    ('Example Rewards Gold', 0, 'AVAILABLE', False),
    (None, 99, 'AVAILABLE', True),
])
def test_fee_identity_does_not_change_binary_payment_rules(tier, amount, availability, paid):
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value='match'))
    assert not matching_paid(facts, 'gold', program_aliases={'Example Rewards'})
    facts.application_routes = [ApplicationRoute(scope='application', prices=[
        RoutePrice(target_tier=tier, amount=amount, currency='USD', availability=availability)])]
    assert matching_paid(facts, 'gold', program_aliases={'Example Rewards'}) is paid


def test_known_aliases_longest_prefix_and_no_suffix_guessing():
    aliases = {'Example', 'Example Rewards', 'Example Club'}
    assert program_tier_key('Example Rewards Gold', aliases) == 'gold'
    assert program_tier_key('Example Club Gold', aliases) == 'gold'
    assert program_tier_key('Other Club Gold', aliases) != 'gold'
    assert program_tier_key('Example Rewards Gold Plus', aliases) != 'gold'


def test_prefixed_price_excluded_from_free_graph_and_paid_in_personal_tree(session_factory):
    with session_factory.begin() as session:
        for label, amount in [('Paid Rewards', 149), ('Free Rewards', 0)]:
            row = _mapping_opportunity(session, slug=label.replace(' ', '-'),
                source_program='Source Club', source_tier='Silver', target_program=label,
                target_tier=label+' Gold', amount=amount, challenge=None)
            facts = deepcopy(row.facts)
            facts['application_routes'][0]['prices'][0]['target_tier'] = label+' Gold'
            row.facts = facts
    with session_factory() as session:
        state = graph_state(session)
        source = 'source club::silver'
        service = WorkflowRouteService(session, state=state)
        query = MatchingQuery(starting_tier_ids=[identity_id('tier', source)])
        all_results = service.query(query)
        assert {step['to']:step['paid'] for step in all_results['server_steps'].values()} == {
            'Paid Rewards Gold': True, 'Free Rewards Gold': False}
        free = service.query(query.model_copy(update={'free_only':True}))
        assert [r['to'] for r in free['server_routes'].values()] == ['Free Rewards Gold']
        forest = matching_forest(session, [source], state=state)
        labels = PersonalizedMatchService(session)._edge_fees(forest.roots)
        assert {row.target_node_id: row.labels for row in labels} == {
            'paid rewards::gold':['付费'], 'free rewards::gold':['免费']}


def test_overlapping_historical_target_header_matches_known_application_price():
    from journeyplus.membership.normalization import target_program_aliases
    from journeyplus.product.brief_data import fee_view
    tiers = ['KM Rewards Rewards Traveller', 'KM Rewards Rewards Explorer',
             'KM Rewards Rewards Pioneer', 'KM Rewards Pioneer']
    aliases = target_program_aliases('KM Rewards', tiers)
    assert program_tier_key(tiers[2], aliases) == 'pioneer'
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value='match'),
        cost=FactField(value='按目标等级收取申请费：Traveller 39欧元，Explorer 69欧元，Pioneer 129欧元。'),
        application_routes=[ApplicationRoute(scope='信用卡申请', eligibility='符合卡种条件', prices=[
            RoutePrice(target_tier='Pioneer', amount=129, currency='EUR', availability='CONDITIONAL')])])
    before = facts.model_dump()
    assert matching_paid(facts, 'pioneer', program_aliases=aliases) is True
    view=fee_view(facts)
    assert view.label == '付费' and not view.incomplete
    assert facts.model_dump() == before


def test_optional_upgrade_does_not_become_known_application_fee():
    facts=FactSet(event_id=uuid4(), what_happened=FactField(value='match'),
        cost=FactField(value='申请费未公布，可选升级另付 USD 50'),
        application_routes=[ApplicationRoute(scope='申请', prices=[
            RoutePrice(target_tier='Gold', amount=50, currency='USD', availability='CONDITIONAL')])])
    assert matching_paid(facts, 'gold') is None
