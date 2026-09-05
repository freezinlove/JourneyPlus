from __future__ import annotations

from uuid import UUID
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


class DetailRequest(StrictModel):
    ref:str
    version_ref:str|None=None


class SeenRequest(StrictModel):
    result_id:UUID
    idempotency_key:str=Field(min_length=1,max_length=100)


def knowledge_router(factory,provider,*,ttl_hours=24,max_calls=3,researcher=None):
    router=APIRouter(prefix="/v2")
    workspace=WorkspaceService(factory,provider,ttl_hours=ttl_hours,max_calls=max_calls,researcher=researcher)
    waiting=WorkspaceWaitService(factory)

    def run(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except (WorkspaceError,LookupError,ValueError) as exc:raise HTTPException(409,str(exc)) from exc

    @router.post("/agent/workspaces")
    def create_workspace():return workspace.create()

    @router.get("/agent/workspaces/{id}")
    def read_workspace(id:UUID):return run(workspace.read,id)

    @router.post("/agent/workspaces/{id}/messages")
    def message(id:UUID,request:MessageRequest):return run(workspace.message,id,request)

    @router.post("/agent/workspaces/{id}/focus")
    def focus(id:UUID,request:FocusRequest):return run(workspace.focus,id,request.ref,request.presentation_id,request.expected_revision)

    @router.post("/agent/workspaces/{id}/confirm")
    def confirm(id:UUID,request:ConfirmRequest):return run(workspace.confirm,id,request)

    @router.post("/agent/workspaces/{id}/details")
    def detail(id:UUID,request:DetailRequest):
        with factory() as s:
            row=run(workspace._load,s,id);state=row.state;refs=ReferenceMap(state)
            if request.ref not in refs.entries:raise HTTPException(404,"对象未在此工作区披露")
            ref=refs.decode(request.ref)
            if ref in state["routes"]:
                route=state["routes"][ref]
                steps=[state["steps"][x] for x in route["step_refs"]]
                activities=[run(ActivityReadService(s).detail,UUID(x["activity_ref"]),UUID(x["version_ref"])) for x in steps]
                return {"type":"route","route":route,"steps":steps,"activities":activities,"research":state.get("research",{})}
            if ref in state.get("activities",{}):
                version=refs.decode(request.version_ref) if request.version_ref else state["activities"][ref]["version_ref"]
                return {"type":"activity","activity":run(ActivityReadService(s).detail,UUID(ref),UUID(version))}
            raise HTTPException(404,"此引用没有独立详情")

    @router.get("/catalog")
    def catalog(q:str=Query(min_length=1,max_length=300)):
        with factory() as s:return CatalogService(s).search(q)

    @router.get("/activities")
    def activities(limit:int=Query(default=20,ge=1,le=50),offset:int=Query(default=0,ge=0)):
        with factory() as s:
            rows=list(s.scalars(select(Activity).where(Activity.current_version_id.is_not(None),Activity.merged_into_id.is_(None)).order_by(Activity.updated_at.desc(),Activity.id).offset(offset).limit(limit+1)))
            reader=ActivityReadService(s)
            return {"activities":[reader.detail(a.id) for a in rows[:limit]],"has_more":len(rows)>limit}

    @router.get("/activities/{id}")
    def activity(id:UUID,version_ref:UUID|None=None):
        with factory() as s:return run(ActivityReadService(s).detail,id,version_ref)

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
