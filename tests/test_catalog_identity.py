from sqlalchemy import select
from tests.test_knowledge import knowledge_session
from tests.test_knowledge_routes import edge
from journeyplus.knowledge.publication import CatalogService
from journeyplus.knowledge.models import MembershipProgram, MembershipTier
from journeyplus.knowledge.catalog_identity import route_identities
from journeyplus.knowledge.routes import RouteQuery, RouteService


def test_reviewed_program_spelling_connects_exact_tier_and_prevents_alias_cycle(knowledge_session):
    s=knowledge_session;c=CatalogService(s)
    p=c.program('Lotusmiles (Vietnam Airlines)')
    q=MembershipProgram(canonical_key='vietnam airlines lotusmiles',display_name='Vietnam Airlines Lotusmiles',category='AIRLINE')
    s.add(q);s.flush()  # Reproduce duplicate IDs created by the historical importer.
    a=c.tier(p.id,'Vietnam Airlines Lotusmiles GOLD');b=c.tier(q.id,'Gold')
    root,_=edge(s,target_tier=a.id)
    _,target=edge(s,source_tier=b.id)
    edge(s,source_tier=b.id,target_tier=a.id)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    routes=list(result['server_routes'].values())
    assert len(routes)==1 and routes[0]['step_count']==2
    first,second=[result['server_steps'][ref] for ref in routes[0]['step_refs']]
    assert first['to_tier_id']==second['from_tier_id']
    assert first['target_category']=='AIRLINE'
    assert result['coverage']['search_complete']
    assert s.get(MembershipTier,a.id) and s.get(MembershipTier,b.id)  # Preserve historical IDs.
    assert len(c.search('Lotusmiles')['programs'])==1


def test_only_proven_table_labels_join_tiers_and_never_guess_rank(knowledge_session):
    s=knowledge_session;c=CatalogService(s);p=c.program('Example Rewards')
    long=c.tier(p.id,'Rewards Gold');short=c.tier(p.id,'Gold');higher=c.tier(p.id,'Gold Elite Plus')
    c.alias('Gold',p.id,higher.id)  # Ordinary ambiguous aliases cannot equate rank.
    def identities():
        return route_identities(s,{p.id:p},{t.id:t for t in s.scalars(select(MembershipTier))})[0]
    assert identities()[long.id]!=identities()[short.id]
    before=RouteService(s).evaluation_context()
    c.alias('Gold',p.id,long.id).origin='OFFICIAL_TABLE_TARGET_LABEL';s.flush()
    result=identities()
    assert result[long.id]==result[short.id]!=result[higher.id]
    assert RouteService(s).evaluation_context()!=before
