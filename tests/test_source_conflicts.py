from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import pytest
from journeyplus.models import SourceItem,DocumentVersion,now_utc
from journeyplus.knowledge.contracts import DocumentBinding,PriceDraft
from journeyplus.knowledge.sources import section_document,create_evidence,require_knowledge_content
from journeyplus.knowledge.publication import PublicationService
from journeyplus.knowledge.routes import RouteService,RouteQuery
from tests.test_knowledge import knowledge_session,fixture_draft


def test_independent_conflicting_source_prices_publish_without_effective_total(knowledge_session):
    s=knowledge_session;draft,doc,_=fixture_draft(s)
    item=s.get(SourceItem,doc.source_item_id)
    second_item=SourceItem(source_id=item.source_id,external_id=str(uuid4()),discovered_url='https://example.com/other-terms',
        canonical_url='https://example.com/other-terms',observed_at=now_utc())
    s.add(second_item);s.flush()
    second=DocumentVersion(source_item_id=second_item.id,canonical_url=second_item.canonical_url,fetched_at=now_utc(),
        raw_hash=str(uuid4()),normalized_hash=str(uuid4()),parser_version='fixture',content_type='text/plain',
        normalized_body='B Gold: EUR 250',storage_mode='FULL')
    s.add(second);s.flush();section=section_document(s,second.id)[0];evidence=create_evidence(s,section.id,section.body)
    draft.documents.append(DocumentBinding(document_version_id=second.id,role='OFFICIAL_SUPPORT'))
    price=deepcopy(draft.options[0].prices[1].model_dump(mode='json'))
    price.update(key='other-source-gold',amount='250',raw_text=section.body,evidence_ids=[str(evidence.id)])
    draft.options[0].prices.append(PriceDraft.model_validate(price))
    PublicationService(s).publish(draft)
    mapping=draft.options[0].mappings[1]
    result=RouteService(s).query(RouteQuery(starting_tier_ids=mapping.source_scope.tier_ids,target_tier_id=mapping.target_tier_id))
    route=next(iter(result['server_routes'].values()))
    assert route['cost']['state']=='CONFLICT' and route['cost']['totals']==[]
    assert {Decimal(item['amount']) for item in route['cost']['conditional_items']}=={Decimal(200),Decimal(250)}


@pytest.mark.parametrize('url',['https://statusmatcher.com/report/1','https://www.statusmatcher.com/company/a'])
def test_experience_cannot_be_used_as_published_official_rules(url):
    with pytest.raises(ValueError,match='temporary workspace'):
        require_knowledge_content(DocumentVersion(canonical_url=url,normalized_body='Someone reported success',storage_mode='normalized_text'))


def test_unexpanded_source_table_prevents_complete_coverage_claim(knowledge_session):
    from journeyplus.knowledge.contracts import ValidationNote
    from journeyplus.knowledge.reads import ActivityReadService
    s=knowledge_session;draft,_,evidence=fixture_draft(s)
    draft.validation_notes=[ValidationNote(code='MAPPING_TABLE_INCOMPLETE',group_ref='table-group-fixture',mapping_count=8,evidence_ids=[evidence.id])]
    PublicationService(s).publish(draft)
    mapping=draft.options[0].mappings[0]
    result=RouteService(s).query(RouteQuery(starting_tier_ids=mapping.source_scope.tier_ids,target_tier_id=mapping.target_tier_id))
    assert result['coverage']['incomplete_published_activity_count']==1
    assert result['coverage']['search_complete'] is False
    material=ActivityReadService(s).materials(selector={'ref':str(draft.activity_id)},question='来源会籍名单')
    assert 'SOURCE_MAPPING' in material['data']['activities'][0]['unresolved_aspects']
