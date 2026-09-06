from decimal import Decimal
import pytest
from journeyplus.knowledge.price_quarantine import quarantine_unproven_prices
from journeyplus.knowledge.publication import PublicationService
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.knowledge.routes import RouteService,RouteQuery
from tests.test_knowledge import knowledge_session,fixture_draft


def test_unproven_price_stays_unknown_and_other_target_survives(knowledge_session):
    s=knowledge_session;draft,_,_=fixture_draft(s);publication=PublicationService(s)
    bad=draft.options[0].prices[0];bad.raw_text='Silver fee: EUR 100 (invented caption)'
    result=quarantine_unproven_prices(publication,draft)
    assert result.options[0].prices[0].known_state=='UNKNOWN'
    assert result.options[0].prices[0].amount is None
    assert 'invented' not in result.options[0].prices[0].raw_text
    assert result.options[0].prices[1].amount==Decimal(200)
    version=publication.publish(result)
    detail=ActivityReadService(s).detail(draft.activity_id)
    assert len(detail['validation_notes'])==1
    assert version.validation_errors[0]['code']=='PRICE_EVIDENCE_WITHHELD'
    mapping=draft.options[0].mappings[0]
    routes=RouteService(s).query(RouteQuery(starting_tier_ids=mapping.source_scope.tier_ids,target_tier_id=mapping.target_tier_id))
    assert routes['server_routes']
    for route in routes['server_routes'].values():
        assert not route['cost']['is_proven_free']
        assert route['cost']['state']!='COMPLETE'


def test_price_withholding_cannot_bypass_invalid_mapping(knowledge_session):
    s=knowledge_session;draft,_,_=fixture_draft(s)
    draft.options[0].prices[0].raw_text='invented fee'
    source=draft.options[0].source_scope
    source.kind='CATEGORY_RULE';source.program_id=None;source.tier_ids=[];source.category='AIRLINE';source.rule_text='All airlines'
    with pytest.raises(ValueError,match='broad-category'):
        quarantine_unproven_prices(PublicationService(s),draft)
