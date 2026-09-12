"""Brief lists must keep facts and brief content on the same published version."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from journeyplus.contracts import Brief
from journeyplus.models import ArticleOpportunityRecord, BriefRecord, FactSetRecord, StatusEvent
from journeyplus.product.api import create_product_app
from tests.test_agent_workflow_reads import original_factory, seed


@pytest.mark.parametrize(
    'pointer, current_briefs, expected_title',
    [
        ('old', False, None),
        ('none', False, None),
        ('old', True, 'Current brief 2'),
        ('none', True, 'Current brief 2'),
        ('selected', True, 'Current brief 1'),
    ],
)
def test_brief_list_matches_current_facts_and_detail(
    original_factory, pointer, current_briefs, expected_title,
):
    article_id = seed(original_factory)
    with original_factory.begin() as session:
        event = StatusEvent(created_from_key=str(uuid4()), program='Official Rewards', summary='summary')
        session.add(event)
        session.flush()
        facts = json.loads(json.dumps(session.get(ArticleOpportunityRecord, article_id).facts))
        facts['event_id'] = str(event.id)
        records = []
        for version in (1, 2):
            record = FactSetRecord(event_id=event.id, version=version, schema_version='5', facts=facts)
            session.add(record)
            session.flush()
            records.append(record)

        def add_brief(record, version, title):
            content = Brief(
                fact_set_id=record.id, title=title, title_fact_keys=['what_happened'],
                summary=title, summary_fact_keys=['what_happened'],
            )
            brief = BriefRecord(
                fact_set_id=record.id, version=version, schema_version='1',
                content=content.model_dump(mode='json'),
            )
            session.add(brief)
            session.flush()
            return brief

        old = add_brief(records[0], 1, 'Old brief')
        selected = None
        if current_briefs:
            selected = add_brief(records[1], 1, 'Current brief 1')
            add_brief(records[1], 2, 'Current brief 2')
        event.current_fact_set_id = records[1].id
        event.current_brief_id = old.id if pointer == 'old' else selected.id if pointer == 'selected' else None
        event_id, fact_id, brief_pointer = event.id, event.current_fact_set_id, event.current_brief_id
        old_fact_id = records[0].id

    # Exercise the real read endpoints without running product maintenance.
    client = TestClient(create_product_app(original_factory))
    response = client.get('/v1/briefs')
    assert response.status_code == 200, response.text
    items = response.json()['items']
    official = [item for item in items if item['source'] == 'STATUS_EVENT']
    assert len(official) == (1 if expected_title else 0)
    if expected_title:
        assert official[0]['opportunity_id'] == str(fact_id)
        assert official[0]['title'] == expected_title
        assert official[0]['summary'] == expected_title

    detail = client.get(f'/v2/activities/{event_id}')
    assert detail.status_code == 200, detail.text
    assert detail.json()['version_ref'] == str(fact_id)
    briefs = detail.json()['briefs']
    assert [brief['content']['title'] for brief in briefs] == ([expected_title] if expected_title else [])
    historical = client.get(f'/v2/activities/{event_id}', params={'version_ref': str(old_fact_id)})
    assert historical.status_code == 200, historical.text
    assert historical.json()['briefs'][0]['content']['title'] == 'Old brief'
    with original_factory() as session:
        event = session.get(StatusEvent, event_id)
        assert (event.current_fact_set_id, event.current_brief_id) == (fact_id, brief_pointer)
