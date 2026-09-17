from uuid import uuid4
from journeyplus.contracts import FactSet, FactField, ApplicationRoute
from journeyplus.facts.service import _normalize_statusmatch_action_links
from journeyplus.product.brief_data import action_links


def test_root_links_are_canonical_before_persistence_and_deduplicated():
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value="Status match"), action_link=FactField(value='https://KENYA-AIRWAYS.statusmatch.com'),
        application_routes=[ApplicationRoute(scope='airline', action_link='https://kenya-airways.statusmatch.com/')])
    normalized = _normalize_statusmatch_action_links(facts, {'https://kenya-airways.statusmatch.com/'})
    assert normalized.model_dump(mode='json')['action_link']['value'] == 'https://kenya-airways.statusmatch.com/'
    assert action_links(normalized) == ['https://kenya-airways.statusmatch.com/']
    assert _normalize_statusmatch_action_links(normalized, {'https://kenya-airways.statusmatch.com/'}) == normalized


def test_output_preserves_distinct_paths_and_parameters():
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value="Status match"), action_link=FactField(value='https://example.com'), application_routes=[
        ApplicationRoute(scope='one', action_link='https://example.com/?channel=one'),
        ApplicationRoute(scope='two', action_link='https://example.com/apply')])
    assert action_links(facts) == ['https://example.com/', 'https://example.com/?channel=one', 'https://example.com/apply']


def test_root_normalization_keeps_query_and_fragment():
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value="Status match"), action_link=FactField(value='https://KENYA-AIRWAYS.statusmatch.com?channel=one#apply'))
    result = _normalize_statusmatch_action_links(facts, {'https://kenya-airways.statusmatch.com/'})
    assert result.action_link.value == 'https://kenya-airways.statusmatch.com/?channel=one#apply'
