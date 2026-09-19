from copy import deepcopy
from datetime import datetime, UTC
from journeyplus.contracts import FactSet
from journeyplus.models import ArticleOpportunityRecord
from journeyplus.knowledge.workflow_knowledge import catalog
from journeyplus.knowledge.workflow_routes import WorkflowRouteService
from journeyplus.knowledge.simple_matching import MatchingQuery
from tests.test_agent_workflow_reads import original_factory, seed


def setup_opportunity(factory):
    identity = seed(factory, source_program='Malaysia Airlines Enrich', source_tier='Gold',
                    target_program='Lufthansa Miles & More', target_tier='Senator')
    with factory.begin() as session:
        row = session.get(ArticleOpportunityRecord, identity)
        facts = deepcopy(row.facts)
        facts['status_mappings'] = []
        facts['matching_opportunities'] = [{
            'source_program': 'Malaysia Airlines Enrich', 'source_qualification': 'Enrich 精英会员',
            'source_tiers': [], 'possible_target_tiers': ['Frequent Traveller', 'Senator']}]
        row.facts = FactSet.model_validate(facts).model_dump(mode='json')
    return identity


def query(session, program='Malaysia Airlines Enrich', tier='Gold', **kwargs):
    from journeyplus.membership.identity import canonical_program, canonical_tier
    programs, tiers, _ = catalog(session)
    p = next(p for p in programs if p.display_name == canonical_program(program))
    t = next(t for t in tiers if t.program_id == p.id and t.display_name == canonical_tier(program, tier))
    return WorkflowRouteService(session).query(MatchingQuery(starting_tier_ids=[t.id], **kwargs))


def test_uncertain_is_one_terminal_candidate_and_not_a_transfer(original_factory):
    setup_opportunity(original_factory)
    seed(original_factory, source_program='Lufthansa Miles & More', source_tier='Senator', target_program='Flying Blue', target_tier='Gold')
    with original_factory() as session:
        result = query(session)
        assert len(result['server_routes']) == 1
        route = next(iter(result['server_routes'].values()))
        assert route['classification'] == 'UNKNOWN' and route['terminal']
        step = result['server_steps'][route['step_refs'][0]]
        assert step['mapping_status'] == 'UNCONFIRMED'
        assert step['possible_target_tiers'] == ['Frequent Traveller', 'Senator']
        assert 'Flying Blue' not in step['to']
        assert 'UNKNOWN' in result['presentation_classes']
        assert step['to_tier_id'].startswith('opportunity:')
        assert not query(session, program='Marriott Bonvoy', tier='Platinum')['server_routes']


def test_expired_and_source_restricted_opportunities_are_excluded(original_factory):
    identity = setup_opportunity(original_factory)
    with original_factory.begin() as session:
        row = session.get(ArticleOpportunityRecord, identity)
        facts = deepcopy(row.facts)
        facts['matching_opportunities'][0]['source_tiers'] = ['Platinum']
        row.facts = facts
    with original_factory() as session:
        assert not query(session)['server_routes']
    with original_factory.begin() as session:
        session.get(ArticleOpportunityRecord, identity).archived_at = datetime.now(UTC)
    with original_factory() as session:
        assert not query(session, tier='Platinum')['server_routes']


def test_old_factsets_default_to_no_opportunities(original_factory):
    identity = seed(original_factory)
    with original_factory() as session:
        assert FactSet.model_validate(session.get(ArticleOpportunityRecord, identity).facts).matching_opportunities == []


def test_article_extraction_preserves_uncertain_relationship_without_mapping():
    from types import SimpleNamespace
    from uuid import uuid4
    from journeyplus.article_pipeline.contracts import ArticleOpportunityExtraction
    from journeyplus.article_pipeline.interpretation import ArticleInterpreter
    extracted = ArticleOpportunityExtraction.model_validate({
        'opportunity_index': 0, 'program': 'Lufthansa Miles & More',
        'opportunity_kind': 'STATUS_MATCH', 'summary': 'Enrich 精英会员可申请',
        'what_happened': {'value': 'Enrich 精英会员可获得 Frequent Traveller 或 Senator'},
        'matching_opportunities': [{'source_program': 'Malaysia Airlines Enrich',
            'source_qualification': '精英会员', 'possible_target_tiers': ['Frequent Traveller', 'Senator']}]})
    facts = ArticleInterpreter._to_fact_set(SimpleNamespace(id=uuid4(), canonical_url='https://example.com/article'), uuid4(), extracted)
    assert facts.status_mappings == []
    assert len(facts.matching_opportunities) == 1
    assert facts.matching_opportunities[0].source_tiers == []


def test_agent_can_present_opportunity_and_brief_keeps_qualification(original_factory, session_factory):
    from tests.test_agent_workflow_reads import context, call
    from journeyplus.product.opportunities import PersonalizedMatchService
    identity = setup_opportunity(original_factory)
    runtime, store, ctx = context(session_factory, original_factory)
    result = call(runtime, ctx, 'routes.evaluate', {'operation': 'search', 'query': {
        'sources': {'mode': 'explicit', 'identities': [{'program_name': 'Malaysia Airlines Enrich', 'tier_name': 'Gold'}]}}})
    assert result.data['candidates'][0]['constraint_match'] == 'UNKNOWN'
    assert '具体等级待确认' in result.data['candidates'][0]['uncertainty_note']
    shown = call(runtime, ctx, 'display.present', {'blocks': [{'type': 'route_graph', 'object_refs': result.data['route_refs']}], 'complete': True})
    with original_factory() as session:
        detail = PersonalizedMatchService(session).detail(identity, include_current_path=False)
        assert detail.facts.matching_opportunities[0].source_qualification == 'Enrich 精英会员'
        assert detail.facts.status_mappings == []


def test_filters_do_not_turn_possible_targets_into_proven_matches(original_factory):
    from journeyplus.knowledge.workflow_knowledge import identity_id
    from journeyplus.membership.identity import canonical_program
    from journeyplus.membership.normalization import normalize_key
    setup_opportunity(original_factory)
    with original_factory() as session:
        assert not query(session, free_only=True)['server_routes']  # fixture is paid
        key = normalize_key(canonical_program('Lufthansa Miles & More'))
        selected = query(session, target_tier_id=identity_id('tier', key+'::senator'))
        assert len(selected['server_routes']) == 1
        assert next(iter(selected['server_routes'].values()))['classification'] == 'UNKNOWN'
        assert not query(session, target_tier_id=identity_id('tier', key+'::hon circle'))['server_routes']
