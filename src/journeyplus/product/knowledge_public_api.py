"""AIWorkflow activities, briefs and graph: no Agent or model lifecycle."""
from uuid import UUID
from fastapi import APIRouter,HTTPException,Query
from journeyplus.knowledge.workflow_knowledge import WorkflowKnowledgePort, WorkflowActivityReader
from journeyplus.knowledge.workflow_explore import search_catalog, explore as explore_query, opportunity_reference
from journeyplus.knowledge.simple_matching import MatchingQuery as RouteQuery


def public_knowledge_router(factory=None,*,knowledge=None):
    router=APIRouter(prefix='/v2');port=knowledge or WorkflowKnowledgePort(factory)

    @router.get('/membership/filters')
    def filters():
        with port.read() as s:
            programs, _, _ = port.catalog(s)
            values=sorted({p.alliance for p in programs if p.alliance})
            return {'alliances':values,'alliance_metadata_available':bool(values)}

    @router.get('/membership/catalog')
    def catalog(text:str=Query(min_length=2,max_length=100)):
        with port.read() as s:return search_catalog(s,text,limit=20)

    @router.get('/activities')
    def activities(limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0),view:str='detail'):
        with port.read() as s:
            reader=WorkflowActivityReader(s)
            rows=reader.locate(limit=limit,offset=offset)
            details=[reader.detail(row.id) for row in rows[:limit]]
            if view=='cards':details=[{k:d.get(k) for k in ('ref','version_ref','name','kind','is_current','updated_at','card')} for d in details]
            return {'activities':details,'has_more':len(rows)>limit}

    @router.get('/activities/{identity}')
    def activity(identity:UUID,version_ref:UUID|None=None,view:str=Query('detail',pattern='^(detail|path_detail)$')):
        try:
            with port.read() as s:
                detail=WorkflowActivityReader(s).detail(identity,version_ref)
                if view=='path_detail':
                    return {key:detail.get(key) for key in ('ref','version_ref','action_links','brief_url','updated_at','fee')}
                return detail
        except LookupError as error:raise HTTPException(409,str(error)) from error
        except ValueError as error:raise HTTPException(409,str(error)) from error

    @router.get('/activities/{identity}/history')
    def history(identity:UUID,before_version:int|None=Query(None,ge=1),limit:int=Query(10,ge=1,le=20)):
        with port.read() as s:return WorkflowActivityReader(s).history(identity,before_version=before_version,limit=limit)

    @router.get('/activities/{identity}/brief')
    def brief(identity:UUID,version_ref:UUID|None=None):
        try:
            with port.read() as s:return WorkflowActivityReader(s).brief_detail(identity,version_ref)
        except (LookupError,ValueError) as error:raise HTTPException(409,str(error)) from error

    @router.post('/explore/query')
    def explore(query:RouteQuery):
        try:
            # Return one computed snapshot; subsequent browser pagination is local.
            with port.read() as s:return explore_query(s,query)
        except (LookupError,ValueError) as error:raise HTTPException(409,str(error)) from error

    @router.get('/legacy/opportunities/{identity}')
    def legacy(identity:UUID):
        with port.read() as s:return opportunity_reference(s,identity)

    return router
