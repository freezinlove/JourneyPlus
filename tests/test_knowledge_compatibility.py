from uuid import uuid4
from journeyplus.models import StatusEvent
from journeyplus.knowledge.migration import _link,migration_manifest
from journeyplus.knowledge.compatibility import legacy_opportunity
from journeyplus.knowledge.publication import PublicationService
from tests.test_knowledge import knowledge_session,fixture_draft


def test_exact_identity_required_and_unpublished_is_not_replacement(knowledge_session):
    s=knowledge_session;draft,_,_=fixture_draft(s)
    old=StatusEvent(created_from_key=str(uuid4()),program='B',summary='old')
    s.add(old);s.flush()
    assert legacy_opportunity(s,old.id)['status']=='UNRESOLVED'
    _link(s,'status_events',old.id,'','activities',draft.activity_id,'MAPPED','explicit identity')
    assert legacy_opportunity(s,old.id)['status']=='NOT_PUBLISHED'
    version=PublicationService(s).publish(draft)
    result=legacy_opportunity(s,old.id)
    assert result['status']=='RESOLVED' and result['version_ref']==str(version.id)
    assert legacy_opportunity(s,uuid4())['status']=='NOT_FOUND'
    manifest=migration_manifest(s)
    assert manifest['unclassified_tables']==[]
    assert manifest['replacement_counts']=={'RESOLVED':1}
    assert 'facts' not in str(manifest['old_entry_replacements'])


def test_mapping_target_is_validated(knowledge_session):
    import pytest
    with pytest.raises(ValueError,match='must exist'):
        _link(knowledge_session,'status_events',uuid4(),'','activities',uuid4(),'MAPPED','invalid')
    with pytest.raises(ValueError,match='Invalid migration'):
        _link(knowledge_session,'status_events',uuid4(),'','agent_interactions',uuid4(),'MAPPED','invalid')


def test_official_card_fact_set_id_follows_event_fk_including_old_versions(knowledge_session):
    from journeyplus.models import FactSetRecord
    s=knowledge_session;draft,_,_=fixture_draft(s)
    event=StatusEvent(created_from_key=str(uuid4()),program='Different old title',summary='old')
    s.add(event);s.flush()
    facts=[FactSetRecord(event_id=event.id,version=v,schema_version='1',facts={}) for v in (1,2)]
    s.add_all(facts);s.flush()
    _link(s,'status_events',event.id,'','activities',draft.activity_id,'MAPPED','explicit')
    for fact in facts:assert legacy_opportunity(s,fact.id)['status']=='NOT_PUBLISHED'
    version=PublicationService(s).publish(draft)
    for fact in facts:
        result=legacy_opportunity(s,fact.id)
        assert result['status']=='RESOLVED'
        assert result['legacy_table']=='fact_sets' and result['legacy_id']==str(fact.id)
        assert result['legacy_event_id']==str(event.id)
        assert result['version_ref']==str(version.id)
    assert migration_manifest(s)['replacement_counts']=={'RESOLVED':3}
