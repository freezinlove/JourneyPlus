from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import os
from uuid import uuid4

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
