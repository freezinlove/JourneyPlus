"""Shared identities must not invent equivalence or change activity conditions."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from journeyplus.membership.identity import (
    directory, resolve_identity, normalize_fact_payload, canonical_program,
)
from journeyplus.membership.alliances import ALLIANCE_MEMBER_AIRLINES, airline_alliance
from journeyplus.knowledge.workflow_knowledge import catalog
from journeyplus.agent.services.identities import IdentityService


@pytest.mark.parametrize('alliance,airline', [
    (alliance, airline) for alliance, airlines in ALLIANCE_MEMBER_AIRLINES.items()
    for airline in sorted(airlines)
])
def test_all_alliance_airlines_have_tiers(alliance, airline):
    found = resolve_identity(airline)
    assert found['status'] == 'OK'
    record = next(p for p in directory()['programs'] if p['key'] == found['program_key'])
    assert record['tiers']
    assert airline_alliance(record['name']) == alliance


def test_every_stored_name_is_retained():
    values = json.loads(Path(__file__).with_name('fixtures').joinpath('membership_names_20260913.json').read_text())
    for program, tiers in values.items():
        for tier in tiers:
            assert resolve_identity(program, tier)['status'] == 'OK', (program, tier)


def test_all_registered_aliases_are_unambiguous_and_idempotent():
    for p in directory()['programs']:
        for alias in [p['name'], *p['aliases']]:
            assert resolve_identity(alias)['program_key'] == p['key']
        for t in p['tiers']:
            for alias in [t['name'], *t['aliases']]:
                result = resolve_identity(p['name'], alias)
                assert result['status'] == 'OK', (p['name'], alias, result)
                assert result['tier_name'] == t['name']


@pytest.mark.parametrize('program,tier,expected', [
    ('汉莎', '金卡', 'Senator'), ('万豪', '白金', 'Platinum Elite'),
    ('凯悦', '环球客', 'Globalist'), ('土航', 'Elite Plus', 'Elite Plus'),
    ('皇家约旦航空', 'Gold', 'Gold Sparrow'), ('Asante Rewards', 'Gold Elite Plus', 'Gold'),
    ('Garuda Indonesia Garuda Miles', 'Platinum', 'Platinum'),
])
def test_program_scoped_aliases(program, tier, expected):
    assert resolve_identity(program, tier)['tier_name'] == expected


def test_no_guessed_colour_or_old_to_new_tier_conversion():
    assert resolve_identity('汉莎', 'Gold')['status'] == 'NOT_FOUND'
    assert resolve_identity('未知航空', '金卡')['status'] == 'NOT_FOUND'
    assert resolve_identity('ANA', '金卡')['status'] == 'NOT_FOUND'
    assert resolve_identity('ITA Airways Miles & More', 'Executive')['tier_name'] == 'Executive'
    assert canonical_program('Air New Zealand Airpoints') != canonical_program('Air New Zealand Koru')
    assert canonical_program('SWISS') != canonical_program('汉莎')


def test_name_only_normalization_preserves_every_other_field_and_row():
    payload = {'status_mappings': [
        {'source_program': '万豪', 'source_tiers': ['白金', '未知等级'],
         'target_tier': 'Gold Elite Plus', 'conditions': ['Only eligible applicants'], 'unknown_future_field': 4},
        {'source_program': '万豪', 'source_tiers': ['白金'],
         'target_tier': 'Gold', 'conditions': ['Different condition']},
    ], 'application_routes': [{'prices': [{'target_tier': 'Gold Elite Plus',
        'amount': 99, 'currency': 'USD', 'regions': ['US']}], 'url': 'https://example.com/apply'}],
        'target_status': {'value': 'Several levels, see table'}, 'extra': {'x': [1, 2]}}
    original = deepcopy(payload)
    result = normalize_fact_payload(payload, 'Asante Rewards')
    expected = deepcopy(payload)
    for row in expected['status_mappings']:
        row['source_program'] = 'Marriott Bonvoy'
        row['source_tiers'][0] = 'Platinum Elite'
        row['target_tier'] = 'Gold'
    expected['application_routes'][0]['prices'][0]['target_tier'] = 'Gold'
    assert result == expected
    assert payload == original
    assert normalize_fact_payload(result, 'Asante Rewards') == result


def test_agent_identity_without_active_opportunity(session_factory):
    with session_factory() as session:
        service = IdentityService(catalog)
        for program, tier in [('汉莎', '金卡'), ('万豪', '白金'), ('华住', '金卡')]:
            value = service.resolve(session, {'program_name': program, 'tier_name': tier}, require_tier=True)
            assert value['status'] == 'OK'
            rebound = service.resolve(session, {'ref': value['tier_ref']}, require_tier=True)
            assert rebound['tier_name'] == value['tier_name']


def test_search_chinese_compound_names_without_losing_tier():
    from journeyplus.membership.identity import matches_identity_query
    assert matches_identity_query('汉莎金卡', 'Lufthansa Miles & More', 'Senator')
    assert matches_identity_query('万豪白金 汉莎金卡', 'Marriott Bonvoy', 'Platinum Elite')
    assert matches_identity_query('万豪白金 汉莎金卡', 'Lufthansa Miles & More', 'Senator')
    assert not matches_identity_query('万豪钛金', 'Marriott Bonvoy', 'Platinum Elite')
    assert resolve_identity('肯尼亚航空 Asante')['program_name'] == 'Asante Rewards'


def test_product_save_uses_the_same_directory_without_active_graph(session_factory):
    from journeyplus.product.holdings import StatusHoldingService
    from journeyplus.product.contracts import StatusHoldingInput
    with session_factory.begin() as session:
        service = StatusHoldingService(session)
        first = service.upsert(StatusHoldingInput(program_key='汉莎', tier_key='金卡'))
        second = service.upsert(StatusHoldingInput(program_key='Lufthansa Miles & More', tier_key='Senator'))
        assert first.id == second.id
        assert second.tier_display_name == 'Senator'


def test_normalized_target_names_still_keep_only_the_highest_tier():
    from types import SimpleNamespace
    from journeyplus.knowledge.simple_matching import highest_targets
    from journeyplus.membership.normalization import normalize_tier
    nodes = {name: SimpleNamespace(program_key='asante rewards', tier_key=normalize_tier(name))
             for name in ['Silver', 'Gold', 'Platinum']}
    assert highest_targets(nodes, list(nodes)) == (['Platinum'], [])
