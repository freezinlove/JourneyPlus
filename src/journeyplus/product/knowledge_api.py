from __future__ import annotations

from uuid import UUID
from typing import Literal
from fastapi import APIRouter,HTTPException,Query
from pydantic import Field
from sqlalchemy import select

from journeyplus.contracts import StrictModel
from journeyplus.agent.workspace import WorkspaceService,WorkspaceWaitService,WorkspaceError,ReferenceMap
from journeyplus.agent.workspace_contracts import MessageRequest,ConfirmRequest
from journeyplus.knowledge.models import Activity
from journeyplus.knowledge.publication import CatalogService
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.knowledge.routes import RouteService,RouteQuery


class FocusRequest(StrictModel):
    ref:str
    presentation_id:str
    expected_revision:int=Field(ge=0)


class ExploreRoutesRequest(StrictModel):
    query:RouteQuery
    expected_revision:int=Field(ge=0)


class BrowseRoutesRequest(StrictModel):
    anchor_ref:str
    presentation_id:str
    cursor:str|None=Field(default=None,max_length=2048)
    expected_revision:int=Field(ge=0)


class DetailRequest(StrictModel):
    ref:str
    version_ref:str|None=None
    presentation_id:str|None=None


class AdoptWaitRequest(StrictModel):
    goal_id:UUID
    result_id:UUID
    expected_revision:int=Field(ge=0)


class SeenRequest(StrictModel):
    result_id:UUID
    idempotency_key:str=Field(min_length=1,max_length=100)


def route_activity_detail(reader,step):
    activity=reader.detail(UUID(step['activity_ref']),UUID(step['version_ref']))
    options=[o for o in activity['options'] if o['ref']==step['option_ref']]
    if len(options)!=1:raise LookupError('路线申请方式与资料版本不一致')
    option=options[0]
    option['mappings']=[m for m in option['mappings'] if m['ref']==step['mapping_ref']]
    if len(option['mappings'])!=1:raise LookupError('路线映射与资料版本不一致')
    price_refs={p['ref'] for key in ('fees','conditional_items','alternative_items') for p in step[key]}
    option['prices']=[p for p in option['prices'] if p['ref'] in price_refs]
    activity['options']=options;activity['detail_scope']='SELECTED_ROUTE_STEP'
    from journeyplus.knowledge.cards import activity_card
    if 'card' in activity:activity['card']=activity_card(activity)
    return activity


def knowledge_router(factory,provider,*,ttl_hours=24,max_calls=3,researcher=None):
    workspace=WorkspaceService(factory,provider,ttl_hours=ttl_hours,max_calls=max_calls,researcher=researcher,plan_route_turns=True)
    waiting=WorkspaceWaitService(factory)
    from journeyplus.agent.delivery import DeliveryService
    delivery=DeliveryService(workspace)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:delivery.pool.shutdown(wait=False,cancel_futures=True)
    router=APIRouter(prefix="/v2",lifespan=lifespan)

    def run(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except (WorkspaceError,LookupError,ValueError) as exc:raise HTTPException(409,str(exc)) from exc

    @router.post("/agent/workspaces")
    def create_workspace():return workspace.create()

    @router.get("/agent/workspaces/{id}")
    def read_workspace(id:UUID):return run(workspace.read,id)

    @router.post("/agent/workspaces/{id}/messages")
    def message(id:UUID,request:MessageRequest):return run(workspace.message,id,request)

    @router.post('/agent/workspaces/{id}/deliveries')
    def start_delivery(id:UUID,request:MessageRequest):return run(delivery.start,id,request)

    @router.get('/agent/workspaces/{id}/deliveries/{run_id}/events')
    def stream_delivery(id:UUID,run_id:UUID,after:int=0):
        from fastapi.responses import StreamingResponse
        run(delivery.events,id,run_id,after)
        return StreamingResponse(delivery.stream(id,run_id,max(0,after)),media_type='text/event-stream',
            headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @router.post("/agent/workspaces/{id}/focus")
    def focus(id:UUID,request:FocusRequest):return run(workspace.focus,id,request.ref,request.presentation_id,request.expected_revision)

    @router.get('/membership/filters')
    def membership_filters():
        from journeyplus.knowledge.models import MembershipProgram
        with factory() as s:
            alliances=list(s.scalars(select(MembershipProgram.alliance).where(MembershipProgram.alliance.is_not(None)).distinct().order_by(MembershipProgram.alliance)))
            return {'alliances':alliances,'alliance_metadata_available':bool(alliances)}

    @router.get('/legacy/opportunities/{identity}')
    def resolve_legacy_opportunity(identity:UUID):
        from journeyplus.knowledge.compatibility import legacy_opportunity
        with factory() as session:return legacy_opportunity(session,identity)

    @router.get('/membership/catalog')
    def catalog(text:str=Query(min_length=2,max_length=100)):
        with factory() as s:return CatalogService(s).search(text,limit=20)

    @router.post('/agent/workspaces/{id}/routes/explore')
    def explore(id:UUID,request:ExploreRoutesRequest):
        from journeyplus.agent.route_browsing import explore_routes
        return run(explore_routes,workspace,id,request)

    @router.post('/agent/workspaces/{id}/routes/browse')
    def browse(id:UUID,request:BrowseRoutesRequest):
        from journeyplus.agent.route_browsing import browse_routes
        return run(browse_routes,workspace,id,request)

    @router.post("/agent/workspaces/{id}/confirm")
    def confirm(id:UUID,request:ConfirmRequest):return run(workspace.confirm,id,request)

    @router.post('/agent/workspaces/{id}/wait-result')
    def adopt_wait_result(id:UUID,request:AdoptWaitRequest):
        return run(workspace.adopt_wait_result,id,request.goal_id,request.result_id,request.expected_revision)

    @router.post("/agent/workspaces/{id}/details")
    def detail(id:UUID,request:DetailRequest):
        with factory() as s:
            row=run(workspace._load,s,id);state=row.state;refs=ReferenceMap(state)
            if request.ref not in refs.entries:raise HTTPException(404,"对象未在此工作区披露")
            ref=refs.decode(request.ref)
            research=[]
            if request.presentation_id:
                from journeyplus.agent.workspace_models import WorkspaceMessage
                message=s.scalar(select(WorkspaceMessage).where(WorkspaceMessage.workspace_id==id,WorkspaceMessage.content['id'].as_string()==request.presentation_id))
                presentation=message.content if message else state.get('browse_presentations',{}).get(request.presentation_id)
                if presentation is None:raise HTTPException(404,'展示已过期或不存在')
                matched=[]
                for block in presentation.get('blocks',[]):
                    allowed=set(block.get('subject_refs',[]))|set(block.get('payload',{}).get('steps',{}))|set(block.get('payload',{}).get('nodes',{}))
                    if request.ref in allowed:matched.append(refs.decode(block.get('payload',{})))
                if not matched:raise HTTPException(404,'对象不属于该回答')
                step_refs=set(state.get('routes',{}).get(ref,{}).get('step_refs',[]))|set(state.get('nodes',{}).get(ref,{}).get('step_refs',[]))|{ref}
                research=[o for payload in matched for o in payload.get('research',[]) if o['step_ref'] in step_refs or o.get('activity_ref')==ref]

            if ref in state["routes"]:
                route=state["routes"][ref]
                steps=[state["steps"][x] for x in route["step_refs"]]
                activities=[run(route_activity_detail,ActivityReadService(s),x) for x in steps]
                return {"type":"route","route":route,"steps":steps,"activities":activities,"research":research}
            if ref in state.get('nodes',{}):
                node=state['nodes'][ref]
                steps=[state['steps'][sid] for sid in node['step_refs']]
                return {'type':'node','node':node,'research':research,'alternatives':[
                    {'step':step,'activity':run(route_activity_detail,ActivityReadService(s),step)} for step in steps]}
            if ref in state.get('steps',{}):
                step=state['steps'][ref]
                return {'type':'step','step':step,'research':research,'activity':run(route_activity_detail,ActivityReadService(s),step)}
            if ref in state.get("activities",{}):
                version=refs.decode(request.version_ref) if request.version_ref else state["activities"][ref]["version_ref"]
                return {"type":"activity","research":research,"activity":run(ActivityReadService(s).detail,UUID(ref),UUID(version))}
            raise HTTPException(404,"此引用没有独立详情")

    @router.get("/catalog")
    def catalog(q:str=Query(min_length=1,max_length=300)):
        with factory() as s:return CatalogService(s).search(q)

    @router.get("/activities")
    def activities(limit:int=Query(default=20,ge=1,le=50),offset:int=Query(default=0,ge=0),view:Literal['cards','detail']='detail'):
        with factory() as s:
            rows=list(s.scalars(select(Activity).where(Activity.current_version_id.is_not(None),Activity.merged_into_id.is_(None)).order_by(Activity.updated_at.desc(),Activity.id).offset(offset).limit(limit+1)))
            reader=ActivityReadService(s)
            details=[reader.detail(a.id) for a in rows[:limit]]
            if view=='cards':details=[{k:d[k] for k in ('ref','version_ref','name','kind','is_current','freshness','published_at','card')} for d in details]
            return {"activities":details,"has_more":len(rows)>limit}

    @router.get("/activities/{id}")
    def activity(id:UUID,version_ref:UUID|None=None):
        with factory() as s:return run(ActivityReadService(s).detail,id,version_ref)

    @router.get('/activities/{id}/history')
    def activity_history(id:UUID,before_version:int|None=Query(default=None,ge=1),limit:int=Query(default=10,ge=1,le=20)):
        with factory() as s:return run(ActivityReadService(s).history,id,before_version=before_version,limit=limit)

    @router.post("/routes/query")
    def routes(query:RouteQuery):
        with factory() as s:
            result=run(RouteService(s).query,query)
            return {k:v for k,v in result.items() if not k.startswith("server_")}

    @router.get("/wait-goal")
    def wait_goal():return waiting.current()

    @router.post("/wait-goal/{id}/seen")
    def seen(id:UUID,request:SeenRequest):return run(waiting.seen,id,request.result_id)

    @router.delete("/wait-goal/{id}")
    def cancel(id:UUID):return run(waiting.cancel,id)

    return router
