"""Published activities, briefs and complete graph: no Agent or model lifecycle."""
from uuid import UUID
from fastapi import APIRouter,HTTPException,Query
from sqlalchemy import select
from journeyplus.knowledge.access import KnowledgePort
from journeyplus.knowledge.models import Activity,MembershipProgram
from journeyplus.knowledge.publication import CatalogService
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.knowledge.routes import RouteService,RouteQuery


def public_knowledge_router(factory=None,*,knowledge=None):
    router=APIRouter(prefix='/v2');port=knowledge or KnowledgePort(factory)

    @router.get('/membership/filters')
    def filters():
        with port.read() as s:
            values=list(s.scalars(select(MembershipProgram.alliance).where(MembershipProgram.alliance.is_not(None)).distinct().order_by(MembershipProgram.alliance)))
            return {'alliances':values,'alliance_metadata_available':bool(values)}

    @router.get('/membership/catalog')
    def catalog(text:str=Query(min_length=2,max_length=100)):
        with port.read() as s:return CatalogService(s).search(text,limit=20)

    @router.get('/catalog')
    def catalogue(q:str=Query(min_length=1,max_length=300)):
        with port.read() as s:return CatalogService(s).search(q)

    @router.get('/activities')
    def activities(limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0),view:str='detail'):
        with port.read() as s:
            reader=port.activity_reader(s)
            rows=reader.locate(limit=limit,offset=offset)
            details=[reader.detail(row.id) for row in rows[:limit]]
            if view=='cards':details=[{k:d.get(k) for k in ('ref','version_ref','name','kind','is_current','freshness','published_at','card')} for d in details]
            return {'activities':details,'has_more':len(rows)>limit}

    @router.get('/activities/{identity}')
    def activity(identity:UUID,version_ref:UUID|None=None):
        try:
            with port.read() as s:return port.activity_reader(s).detail(identity,version_ref)
        except LookupError as error:raise HTTPException(409,str(error)) from error
        except ValueError as error:raise HTTPException(409,str(error)) from error

    @router.get('/activities/{identity}/history')
    def history(identity:UUID,before_version:int|None=Query(None,ge=1),limit:int=Query(10,ge=1,le=20)):
        with port.read() as s:return port.activity_reader(s).history(identity,before_version=before_version,limit=limit)

    @router.post('/explore/query')
    def explore(query:RouteQuery):
        with port.read() as s:result=RouteService(s).query(query)
        # Transfer the bounded computed snapshot once. Browser pagination is local
        # and cannot silently recompute against a newer publication or call Agent.
        routes=[{k:v for k,v in route.items() if k not in {'fact_refs','selection_reasons'}} for route in result['server_routes'].values()]
        return {'routes':routes,'steps':result['server_steps'],'snapshot':result['snapshot'],'coverage':result['coverage']}

    @router.get('/legacy/opportunities/{identity}')
    def legacy(identity:UUID):
        from journeyplus.knowledge.compatibility import legacy_opportunity
        with port.read() as s:return legacy_opportunity(s,identity)

    @router.post('/routes/query')
    def query_routes(query:RouteQuery):
        try:
            with port.read() as s:result=RouteService(s).query(query)
            return {key:value for key,value in result.items() if not key.startswith('server_')}
        except (LookupError,ValueError) as error:raise HTTPException(409,str(error)) from error

    return router
