from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import os
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.orm import Session

from journeyplus.models import Base, Source, SourceItem, DocumentVersion, now_utc
from journeyplus.knowledge.contracts import FactValue, KnowledgeDraft, PriceDraft, SourceScope, Temporal
from journeyplus.knowledge.models import (
    Activity, ActivityBrief, ActivityKnowledgeVersion, ApplicationOptionVersion,
    EvidenceReference, OptionMapping, OptionPrice, OptionPriceMapping,
)
from journeyplus.knowledge.publication import CatalogService, PublicationService, StaleKnowledgeBase
from journeyplus.knowledge.sources import section_document, create_evidence, expand_evidence


@pytest.fixture
def knowledge_session():
    url=os.environ.get("JOURNEYPLUS_KNOWLEDGE_TEST_URL", "sqlite+pysqlite:///:memory:")
    engine=create_engine(url)
    if engine.dialect.name=="sqlite":
        @event.listens_for(engine,"connect")
        def foreign_keys(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
    connection=engine.connect();transaction=connection.begin()
    with Session(connection,expire_on_commit=False,join_transaction_mode="create_savepoint") as s:
        yield s
    transaction.rollback();connection.close();engine.dispose()


def fixture_draft(s):
    suffix=str(uuid4())
    source=Source(id=suffix,name="fixture",adapter_type="fixture")
    s.add(source);s.flush()
    item=SourceItem(source_id=source.id,external_id=suffix,discovered_url="https://example.com/terms",
                    canonical_url="https://example.com/terms",observed_at=now_utc())
    s.add(item);s.flush()
    body="# Airline method\n\nA Gold to B Silver: EUR 100.\nA Gold to B Gold: EUR 200.\nNo challenge.\n\nException: matched source status is not accepted.\n\n# Hotel method\n\nH Platinum to B Gold: EUR 50. Four stays in 90 days.\n"
    doc=DocumentVersion(source_item_id=item.id,canonical_url=item.canonical_url,raw_body=body,
                        normalized_body=body,content_type="text/markdown",storage_mode="FULL",
                        raw_hash=suffix,normalized_hash=suffix,parser_version="fixture",fetched_at=now_utc())
    s.add(doc);s.flush()
    sections=section_document(s,doc.id)
    ev=create_evidence(s,sections[1].id,sections[1].body)
    evidence=[str(ev.id)]
    c=CatalogService(s)
    a=c.program("A "+suffix); ag=c.tier(a.id,"Gold")
    b=c.program("B "+suffix); bs=c.tier(b.id,"Silver"); bg=c.tier(b.id,"Gold")
    activity=Activity(identity_key=suffix,primary_program_id=b.id,kind="STATUS_MATCH",edition_key="2026-01")
    s.add(activity);s.flush()
    scope={"kind":"EXACT_TIERS","program_id":str(a.id),"tier_ids":[str(ag.id)],"evidence_ids":evidence}
    draft=KnowledgeDraft.model_validate({"activity_id":str(activity.id),"extraction_key":"fixture-1",
        "facts":{"title":"示例 B 活动","summary":{"known_state":"KNOWN","value":"two targets","evidence_ids":evidence}},
        "documents":[{"document_version_id":str(doc.id),"role":"OFFICIAL_PRIMARY"}],
        "options":[{"logical_key":"airline","label":"航空会籍","method":"MATCH","source_scope":scope,
                    "availability":"AVAILABLE","challenge":{"known_state":"KNOWN","value":{"kind":"NONE"},"evidence_ids":evidence},
                    "mappings":[{"key":key,"source_scope":scope,"target_program_id":str(b.id),"target_tier_id":str(t.id),"availability":"AVAILABLE","evidence_ids":evidence} for key,t in [("silver",bs),("gold",bg)]],
                    "prices":[{"key":key,"charge_key":"application-"+key,"target_tier_id":str(t.id),"mapping_keys":[key],"amount":amount,"currency":"EUR","known_state":"KNOWN","availability":"AVAILABLE","raw_text":f"B {t.display_name}: EUR {amount}","evidence_ids":evidence} for key,t,amount in [("silver",bs,"100"),("gold",bg,"200")]]}]})
    return draft,doc,ev


def test_unknown_is_not_free_or_public():
    assert FactValue[str]().known_state=="UNKNOWN"
    assert SourceScope().kind=="UNKNOWN"
    with pytest.raises(ValidationError): FactValue[str](known_state="KNOWN",value="free")
    with pytest.raises(ValidationError): FactValue[str](known_state="UNKNOWN",value="free")
    with pytest.raises(ValidationError): SourceScope(kind="PUBLIC")
    with pytest.raises(ValidationError): Temporal(precision="DATE",instant="2026-01-01T00:00:00Z")


def test_explicit_edition_review_preserves_history_and_blocks_uncertain_source(knowledge_session):
    from journeyplus.knowledge.identity import ActivityIdentityService,UnresolvedActivityEdition
    s=knowledge_session;draft,doc,evidence=fixture_draft(s)
    version=PublicationService(s).publish(draft);identity=ActivityIdentityService(s)
    kwargs={'reason':'Scoped source review','evidence_ids':[evidence.id],'official_document_ids':[doc.id],
            'expected_version':version.id}
    same=identity.review_edition('status_events','review-source',draft.activity_id,review_id=uuid4(),decision='SAME',**kwargs)
    assert same.id==draft.activity_id
    identity.review_edition('status_events','review-source',draft.activity_id,review_id=uuid4(),decision='UNRESOLVED',**kwargs)
    with pytest.raises(UnresolvedActivityEdition):identity.resolve_source('status_events','review-source',draft.activity_id)
    with pytest.raises(ValueError,match='Year or brand'):
        identity.review_edition('status_events','review-source',draft.activity_id,review_id=uuid4(),decision='NEW',edition_key='2027',**kwargs)
    token=str(uuid4());body='A new round is open. Previous applicants may apply again after the eligibility reset.'
    newdoc=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=body,normalized_body=body,
        content_type='text/markdown',storage_mode='FULL',raw_hash=token,normalized_hash=token,parser_version='fixture',fetched_at=now_utc())
    s.add(newdoc);s.flush();section=section_document(s,newdoc.id)[0];ev=create_evidence(s,section.id,section.body)
    kwargs.update(evidence_ids=[ev.id],official_document_ids=[newdoc.id]);review_id=uuid4()
    fresh=identity.review_edition('status_events','review-source',draft.activity_id,review_id=review_id,decision='NEW',edition_key='round-2',**kwargs)
    assert fresh.id!=draft.activity_id and fresh.current_version_id is None
    assert identity.resolve_source('status_events','review-source',draft.activity_id).id==fresh.id
    assert s.get(Activity,draft.activity_id).current_version_id==version.id
    assert identity.review_edition('status_events','review-source',draft.activity_id,review_id=review_id,decision='NEW',edition_key='round-2',**kwargs).id==fresh.id
    with pytest.raises(ValueError,match='reused'):
        identity.review_edition('status_events','review-source',draft.activity_id,review_id=review_id,decision='NEW',edition_key='different',**kwargs)


def test_edition_signal_is_reviewed_per_document_version(knowledge_session):
    from journeyplus.knowledge.edition_guard import edition_signals
    from journeyplus.knowledge.identity import ActivityIdentityService
    s=knowledge_session;draft,doc,ev=fixture_draft(s);v=PublicationService(s).publish(draft)
    activity=s.get(Activity,draft.activity_id);source=('status_events','signal-source')
    assert edition_signals(s,activity,draft.documents,source)==[]
    token=str(uuid4());body='New round: previous applicants may apply again.'
    newer=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=body,normalized_body=body,
        content_type='text/markdown',storage_mode='FULL',raw_hash=token,normalized_hash=token,parser_version='fixture',fetched_at=now_utc())
    s.add(newer);s.flush();section_document(s,newer.id)
    from journeyplus.knowledge.contracts import DocumentBinding
    bindings=[DocumentBinding(document_version_id=newer.id,role='THIRD_PARTY')]
    signals=edition_signals(s,activity,bindings,source)
    assert signals
    ActivityIdentityService(s).review_edition(*source,activity.id,review_id=uuid4(),decision='SAME',reason='Article quotes historical wording; no new official edition',
        evidence_ids=signals,official_document_ids=[],reviewed_document_ids=[newer.id],expected_version=v.id)
    assert edition_signals(s,activity,bindings,source)==[]
    # A review for this exact document cannot approve a later source version.
    newer2=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=body,normalized_body=body,
        content_type='text/markdown',storage_mode='FULL',raw_hash=str(uuid4()),normalized_hash=str(uuid4()),parser_version='fixture',fetched_at=now_utc())
    s.add(newer2);s.flush();section_document(s,newer2.id)
    assert edition_signals(s,activity,[DocumentBinding(document_version_id=newer2.id,role='THIRD_PARTY')],source)


def test_catalog_aliases_keep_ambiguity(knowledge_session):
    c=CatalogService(knowledge_session)
    a=c.program("Alpha");b=c.program("Beta")
    c.alias("同名",a.id);c.alias("同名",b.id)
    assert len(c.search("同名")["programs"])==2


def test_price_scope_cannot_cross_target(knowledge_session):
    draft,_,_=fixture_draft(knowledge_session)
    data=draft.model_dump(mode="json")
    data["options"][0]["prices"][0]["mapping_keys"]=["gold"]
    with pytest.raises(ValidationError,match="target"): KnowledgeDraft.model_validate(data)


def test_sections_keep_exception_and_are_idempotent(knowledge_session):
    s=knowledge_session;draft,doc,ev=fixture_draft(s)
    before=section_document(s,doc.id)
    assert [x.id for x in before]==[x.id for x in section_document(s,doc.id)]
    expanded=expand_evidence(s,ev.id)
    assert any("not accepted" in x["text"] for x in expanded["sections"])
    assert not any("Four stays" in x["text"] for x in expanded["sections"])
    assert create_evidence(s,before[1].id,ev.quote).id==ev.id
    with pytest.raises(ValueError): create_evidence(s,before[1].id,"invented quote")


def test_atomic_publish_is_idempotent_and_keeps_option_identity(knowledge_session):
    s=knowledge_session;draft,doc,old_ev=fixture_draft(s)
    service=PublicationService(s);v1=service.publish(draft)
    assert service.publish(draft).id==v1.id
    ov1=s.scalar(select(ApplicationOptionVersion).where(ApplicationOptionVersion.knowledge_version_id==v1.id))
    data=draft.model_dump(mode="json");data.update(base_version_id=str(v1.id),extraction_key="fixture-2")
    new_body=doc.normalized_body.replace('B Gold: EUR 200','B Gold: EUR 180')
    new_doc=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=new_body,normalized_body=new_body,content_type='text/markdown',storage_mode='FULL',raw_hash=str(uuid4()),normalized_hash=str(uuid4()),parser_version='fixture',fetched_at=now_utc())
    s.add(new_doc);s.flush();new_sections=section_document(s,new_doc.id)
    new_ev=create_evidence(s,new_sections[1].id,new_sections[1].body)
    import json
    data=json.loads(json.dumps(data).replace(str(old_ev.id),str(new_ev.id)).replace(str(doc.id),str(new_doc.id)))
    data["options"][0]["prices"][1].update(amount="180",raw_text="B Gold: EUR 180")
    v2=service.publish(KnowledgeDraft.model_validate(data))
    ov2=s.scalar(select(ApplicationOptionVersion).where(ApplicationOptionVersion.knowledge_version_id==v2.id))
    assert ov1.option_id==ov2.option_id and ov1.id!=ov2.id
    assert s.get(Activity,draft.activity_id).current_version_id==v2.id
    assert s.scalar(select(OptionPrice.amount).where(OptionPrice.option_version_id==ov1.id,OptionPrice.price_key=="gold"))==Decimal("200")
    assert s.scalar(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==v2.id,ActivityBrief.brief_kind=="UPDATE"))
    from journeyplus.knowledge.reads import ActivityReadService
    reader=ActivityReadService(s)
    newest=reader.history(draft.activity_id,limit=1)
    assert newest['versions'][0]['version_ref']==str(v2.id) and newest['versions'][0]['is_current']
    assert newest['has_more']
    older=reader.history(draft.activity_id,before_version=newest['next_before_version'],limit=1)
    assert older['versions'][0]['version_ref']==str(v1.id) and not older['versions'][0]['is_current']
    assert not older['has_more']
    stale=draft.model_copy(update={"extraction_key":"late-old-extraction"})
    with pytest.raises(StaleKnowledgeBase): service.publish(stale)


def test_evidence_must_belong_to_bound_document(knowledge_session):
    s=knowledge_session;draft,doc,ev=fixture_draft(s)
    other,_,_=fixture_draft(s)
    bad=draft.model_copy(update={"documents":other.documents})
    with pytest.raises(ValueError,match="Evidence not bound"): PublicationService(s).publish(bad)
    assert s.get(Activity,draft.activity_id).current_version_id is None


def test_table_row_expands_with_header_and_footnote(knowledge_session):
    s=knowledge_session;_,doc,_=fixture_draft(s)
    body="# Fees\n\n| Tier | Fee |\n| --- | --- |\n| Gold | EUR 200 |\n\nNote: not available in region X.\n"
    other=DocumentVersion(source_item_id=doc.source_item_id,canonical_url=doc.canonical_url,raw_body=body,
        normalized_body=body,content_type="text/markdown",storage_mode="FULL",raw_hash=str(uuid4()),
        normalized_hash=str(uuid4()),parser_version="fixture",fetched_at=now_utc())
    s.add(other);s.flush();sections=section_document(s,other.id)
    row=next(x for x in sections if x.kind=="ROW" and "Gold" in x.body)
    evidence=create_evidence(s,row.id,row.body)
    content="\n".join(x["text"] for x in expand_evidence(s,evidence.id)["sections"])
    assert "Tier | Fee" in content and "not available" in content


def test_cross_version_mapping_fk(knowledge_session):
    s=knowledge_session;a,_,_=fixture_draft(s);b,_,_=fixture_draft(s)
    av=PublicationService(s).publish(a);bv=PublicationService(s).publish(b)
    price=s.scalar(select(OptionPrice).where(OptionPrice.knowledge_version_id==av.id))
    mapping=s.scalar(select(OptionMapping).where(OptionMapping.knowledge_version_id==bv.id))
    with pytest.raises(DBAPIError):
        with s.begin_nested():
            s.add(OptionPriceMapping(price_id=price.id,mapping_id=mapping.id,option_version_id=price.option_version_id));s.flush()


def test_postgres_published_facts_cannot_be_changed(knowledge_session):
    s=knowledge_session
    if s.bind.dialect.name!="postgresql": pytest.skip("PostgreSQL publication triggers")
    draft,_,_=fixture_draft(s);version=PublicationService(s).publish(draft)
    with pytest.raises(DBAPIError,match="immutable"):
        with s.begin_nested():
            s.execute(text("UPDATE activity_knowledge_versions SET fact_hash='tampered' WHERE id=:id"),{"id":version.id})
    price=s.scalar(select(OptionPrice).where(OptionPrice.knowledge_version_id==version.id))
    with pytest.raises(DBAPIError,match="immutable"):
        with s.begin_nested():
            s.execute(text("UPDATE option_prices SET amount=1 WHERE id=:id"),{"id":price.id})


def test_routes_bind_gold_price_and_report_partial(knowledge_session):
    from journeyplus.knowledge.routes import RouteService, RouteQuery
    s=knowledge_session;draft,_,_=fixture_draft(s);v=PublicationService(s).publish(draft)
    option=draft.options[0];root=option.source_scope.tier_ids[0]
    gold=option.mappings[1].target_tier_id
    q=RouteQuery(starting_tier_ids=[root],target_tier_id=gold,max_amount=Decimal("100"),currency="EUR",allow_challenge=False)
    result=RouteService(s).query(q,snapshot={str(draft.activity_id):str(v.id)})
    card=result["data"]["cards"][0]
    assert card["cost"]["totals"][0]["amount"]=="200.0000"
    assert card["classification"]=="NEARBY" and card["violations"]==["max_amount"]
    limited=RouteService(s).query(q,max_states=0)
    assert not limited["coverage"]["search_complete"]
    assert limited["coverage"]["stopped_reason"]=="STATE_BUDGET"


def test_route_unknown_challenge_never_becomes_none(knowledge_session):
    from journeyplus.knowledge.routes import RouteService, RouteQuery
    s=knowledge_session;draft,_,_=fixture_draft(s)
    data=draft.model_dump(mode="json");data["options"][0]["challenge"]={}
    draft=KnowledgeDraft.model_validate(data);v=PublicationService(s).publish(draft)
    q=RouteQuery(starting_tier_ids=draft.options[0].source_scope.tier_ids,allow_challenge=False)
    result=RouteService(s).query(q,snapshot={str(draft.activity_id):str(v.id)})
    assert all(r["classification"]=="UNKNOWN" and r["challenge"]=="UNKNOWN" for r in result["data"]["cards"])


def test_publication_failure_rolls_back_new_version_and_current_pointer(knowledge_session):
    s=knowledge_session
    draft,_,_=fixture_draft(s)
    first=PublicationService(s).publish(draft)
    first_id=first.id
    data=draft.model_dump(mode='json')
    data.update(base_version_id=str(first_id),extraction_key='injected-publication-failure')
    data['facts']['title']='Updated title for transaction fixture'
    def fail_before_published(session, *_):
        if any(isinstance(row,ActivityKnowledgeVersion) and row.id!=first_id and row.status=='PUBLISHED' for row in session.dirty):
            raise RuntimeError('Injected publication failure')
    event.listen(s,'before_flush',fail_before_published)
    try:
        with pytest.raises(RuntimeError,match='Injected'):
            with s.begin_nested():PublicationService(s).publish(KnowledgeDraft.model_validate(data))
    finally:event.remove(s,'before_flush',fail_before_published)
    assert s.get(Activity,draft.activity_id).current_version_id==first_id
    assert len(list(s.scalars(select(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.activity_id==draft.activity_id))))==1


def test_catalog_alias_ambiguity_and_tier_ownership(knowledge_session):
    from uuid import uuid4
    s=knowledge_session;c=CatalogService(s)
    a=c.program('Alias Program A '+str(uuid4()));b=c.program('Alias Program B '+str(uuid4()))
    alias='共享别名'+str(uuid4());c.alias(alias,a.id);c.alias(alias,b.id)
    result=c.search(alias)
    assert {p['id'] for p in result['programs']}=={str(a.id),str(b.id)}
    tier=c.tier(a.id,'Gold')
    with pytest.raises(ValueError,match='another program'):c.alias('wrong',b.id,tier.id)
    with pytest.raises(ValueError,match='nonempty'):c.alias(' ',a.id)
    assert tier.rank is None


def test_same_alliance_and_tier_name_do_not_create_equivalent_membership(knowledge_session):
    from journeyplus.knowledge.routes import RouteService,RouteQuery
    from journeyplus.knowledge.models import MembershipProgram
    s=knowledge_session;draft,_,_=fixture_draft(s);PublicationService(s).publish(draft)
    source=s.get(MembershipProgram,draft.options[0].mappings[0].source_scope.program_id)
    source.alliance='SKYTEAM'
    other=CatalogService(s).program('Unrelated alliance member '+str(source.id),alliance='SKYTEAM')
    tier=CatalogService(s).tier(other.id,'Gold');s.flush()
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[tier.id]))
    assert result['data']['cards']==[]


def test_explicit_identity_merge_preserves_history_and_blocks_stale_publication(knowledge_session):
    from journeyplus.knowledge.identity import ActivityIdentityService
    s=knowledge_session;draft,_,_=fixture_draft(s)
    version=PublicationService(s).publish(draft)
    source=s.get(Activity,draft.activity_id)
    target=Activity(identity_key=str(uuid4()),primary_program_id=source.primary_program_id,
                    kind=source.kind,edition_key='reviewed-same-edition')
    s.add(target);s.flush()
    evidence=list(draft.facts.summary.evidence_ids)
    # This fixture's summary can be unknown; use an actual mapping reference.
    evidence=evidence or draft.options[0].mappings[0].evidence_ids
    service=ActivityIdentityService(s)
    args=dict(reason='Sources explicitly identify the same offer',evidence_ids=evidence,
              expected_source_version=version.id,expected_target_version=None)
    with pytest.raises(ValueError,match='changed'):
        service.merge(source.id,target.id,**{**args,'expected_source_version':None})
    assert service.merge(source.id,target.id,**args).id==target.id
    assert service.merge(source.id,target.id,**args).id==target.id
    assert source.current_version_id==version.id
    assert service.resolve(source.id).id==target.id
    from journeyplus.knowledge.reads import ActivityReadService
    reader=ActivityReadService(s)
    assert reader.detail(source.id)['ref']==str(target.id)
    historical=reader.detail(source.id,version.id)
    assert historical['version_ref']==str(version.id) and not historical['is_current']
    assert historical['merged_into_ref']==str(target.id)
    with pytest.raises(ValueError,match='canonical'):
        service.merge(target.id,source.id,**args)
    with pytest.raises(StaleKnowledgeBase,match='merged'):
        PublicationService(s).publish(draft)


@pytest.mark.parametrize('restricted', ['mail', 'public_terms'])
def test_source_boundary_also_blocks_preexisting_sections_and_evidence(knowledge_session,restricted):
    s=knowledge_session;draft,_,_=fixture_draft(s)
    doc=s.get(DocumentVersion,draft.documents[0].document_version_id)
    eid=draft.options[0].mappings[0].evidence_ids[0]
    if restricted=='mail':
        doc.storage_mode='restricted_mail_snapshot'
    else:
        doc.canonical_url='https://example.statusmatch.com/terms'
        doc.normalized_body+='\n\n## StatusMatch.Com Terms of Use\nExcluded common tail'
    s.flush()
    with pytest.raises(ValueError):section_document(s,doc.id)
    with pytest.raises(ValueError):expand_evidence(s,eid)
    with pytest.raises(ValueError):PublicationService(s).validate(draft)


def test_mapping_table_groups_keep_rows_and_exclude_unavailable_cells(knowledge_session):
    from journeyplus.knowledge.table_groups import prepare_mapping_groups
    from journeyplus.knowledge.models import MembershipProgram
    s=knowledge_session;draft,_,_=fixture_draft(s)
    prior=s.get(DocumentVersion,draft.documents[0].document_version_id)
    target=s.get(MembershipProgram,draft.options[0].mappings[0].target_program_id)
    body=f'| | {target.display_name} Tier | |\n| Airline | Silver | Gold |\n| **Example Air** Club | Bronze | Diamond |\n| Other Airline | Silver | Not Available |'
    html=f'<table><tr><td></td><td colspan="2">{target.display_name} Tier</td></tr><tr><th>Airline</th><th>Silver</th><th>Gold</th></tr><tr><td>Example Air Club</td><td>Bronze</td><td>Diamond</td></tr><tr><td>Other Airline</td><td>Silver</td><td>Not Available</td></tr></table>'
    doc=DocumentVersion(source_item_id=prior.source_item_id,canonical_url='https://example.statusmatch.com/faq',
        normalized_body=body,raw_body=html,raw_hash=str(uuid4()),normalized_hash=str(uuid4()),
        content_type='text/html',storage_mode='permitted_snapshot',parser_version='test',fetched_at=now_utc())
    s.add(doc);s.flush()
    groups,hints=prepare_mapping_groups(s,doc,section_document(s,doc.id),target.id)
    assert len(groups)==1 and hints[0]['mapping_count']==3
    mappings=next(iter(groups.values()))
    assert all(m['source_scope']['kind']=='EXACT_TIERS' for m in mappings)
    assert len({m['key'] for m in mappings})==3
    assert all(s.get(EvidenceReference,UUID(m['evidence_ids'][0])).document_version_id==doc.id for m in mappings)


def test_mapping_group_keeps_source_footnote_and_its_section_evidence(knowledge_session):
    from journeyplus.knowledge.table_groups import prepare_mapping_groups
    from journeyplus.knowledge.models import MembershipProgram
    s=knowledge_session; draft,_,_=fixture_draft(s)
    prior=s.get(DocumentVersion,draft.documents[0].document_version_id)
    target=s.get(MembershipProgram,draft.options[0].mappings[0].target_program_id)
    body=f'| | {target.display_name} Tier |\n| Airline | Gold |\n| Aer Lingus \\*\\*\\*\\* AerClub | Platinum |\n\n**** Limited to EU/UK Passport holders.'
    html=f'<table><tr><td></td><td>{target.display_name} Tier</td></tr><tr><th>Airline</th><th>Gold</th></tr><tr><td>Aer Lingus **** AerClub</td><td>Platinum</td></tr></table><p>**** Limited to EU/UK Passport holders.</p>'
    doc=DocumentVersion(source_item_id=prior.source_item_id,canonical_url='https://example.statusmatch.com/faq',
        normalized_body=body,raw_body=html,raw_hash=str(uuid4()),normalized_hash=str(uuid4()),
        content_type='text/html',storage_mode='permitted_snapshot',parser_version='test',fetched_at=now_utc())
    s.add(doc);s.flush()
    groups,_=prepare_mapping_groups(s,doc,section_document(s,doc.id),target.id)
    mapping=next(iter(groups.values()))[0]
    assert mapping['availability']=='UNKNOWN'
    condition=mapping['conditions']['items'][0]
    assert condition['value']=='Limited to EU/UK Passport holders.'
    assert len(condition['evidence_ids'])==2
    assert any('Limited to EU/UK' in s.get(EvidenceReference,UUID(ref)).quote for ref in condition['evidence_ids'])


@pytest.mark.parametrize('clause,expected_topic',[
    ('Only Government issued identity document holders for the following countries are eligible: Canada, France.','DOCUMENT_REQUIREMENT'),
    ('Passport holders who are residents of Canada may apply.','RESIDENCY'),
    ('Only residents of Canada may apply.','RESIDENCY'),
])
def test_document_holder_country_is_not_automatically_residency(knowledge_session,clause,expected_topic):
    from types import SimpleNamespace
    s=knowledge_session;draft,_,_=fixture_draft(s)
    value=draft.model_dump(mode='json');evidence=value['options'][0]['evidence_ids'][0] if 'evidence_ids' in value['options'][0] else value['options'][0]['source_scope']['evidence_ids'][0]
    value['facts']['conditions']={'items':[{'condition_id':'country','topic':'RESIDENCY','operator':'IN','value':['Canada'],
        'known_state':'KNOWN','raw_text':clause,'evidence_ids':[evidence]}]}
    class SourceEvidence:
        def get(self,model,id):return SimpleNamespace(quote=clause)
    result=PublicationService(SourceEvidence()).ground_condition_topics(KnowledgeDraft.model_validate(value))
    assert result.facts.conditions.items[0].topic==expected_topic
    if expected_topic=='DOCUMENT_REQUIREMENT':assert result.facts.conditions.items[0].operator=='TEXT'


def test_directory_keeps_user_named_start_when_model_only_asks_about_fees(knowledge_session):
    from journeyplus.knowledge.reads import ActivityReadService
    from journeyplus.knowledge.routes import RouteService,RouteQuery
    s=knowledge_session;draft,_,_=fixture_draft(s);PublicationService(s).publish(draft)
    catalog=CatalogService(s);outside=catalog.program('Outside Airlines');tier=catalog.tier(outside.id,'Gold')
    result=ActivityReadService(s).materials(selector={'ref':str(draft.activity_id)},question='申请费多少钱',
        directory_context='假设我有 Outside Airlines Gold，想找匹配路径。')
    assert str(tier.id) in {row['tier_ref'] for row in result['data']['catalog']}
    # Directory disclosure is not an application mapping or eligibility claim.
    assert not RouteService(s).query(RouteQuery(starting_tier_ids=[tier.id]))['data']['cards']


def test_catalog_resolves_distinctive_tier_without_inventing_acronym(knowledge_session):
    s=knowledge_session;catalog=CatalogService(s)
    p=catalog.program('Royal Jordanian Royal Club');catalog.tier(p.id,'Gold Sparrow')
    other=catalog.program('Another Club');catalog.tier(other.id,'Gold')
    assert [r['id'] for r in catalog.search('RJ Gold Sparrow route')['programs']]==[str(p.id)]
    assert catalog.search('RJ')['programs']==[]
    assert catalog.search('Gold route')['programs']==[]


def test_faq_expansion_preserves_full_answer_without_other_questions(knowledge_session):
    from types import SimpleNamespace
    from uuid import uuid4
    from journeyplus.knowledge.sources import related_section_scope
    questions=['* **How long is status valid?**','You receive 12 months.','Except expired source accounts.',
               '* **How much is the fee?**','The application costs USD 149.']
    rows=[SimpleNamespace(id=uuid4(),kind='PARAGRAPH',body=text,related_section_ids=[]) for text in questions]
    for row in rows:row.related_section_ids=[str(r.id) for r in rows if r!=row]
    assert related_section_scope(rows[1],rows)=={r.id for r in rows[:3]}
    assert related_section_scope(rows[4],rows)=={r.id for r in rows[3:]}
