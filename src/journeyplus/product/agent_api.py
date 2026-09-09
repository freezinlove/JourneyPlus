"""Independent v3 transport. No user-language parsing or workflow imports."""
from journeyplus.agent.harness.execution import blocking_call
import asyncio
import json
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from journeyplus.agent.harness.contracts import DTO
from journeyplus.agent.adapters.persistence import StoreError, TERMINAL


class RunRequest(DTO):
    text: str = Field(min_length=1,max_length=16000)
    client_message_id: str = Field(min_length=1,max_length=100)
    expected_revision: int = Field(ge=0)
    subject_refs: list[str] = Field(default_factory=list,max_length=20)
    focus_ref: str | None = None


class CreateRequest(DTO):
    import_workspace_id: UUID | None = None


class CancelRequest(DTO):
    idempotency_key: str = Field(min_length=1,max_length=100)


class FocusRequest(DTO):
    presentation_ref: str
    object_ref: str
    expected_revision: int


class BrowseRequest(DTO):
    cursor: str = Field(min_length=1,max_length=500)
    expected_revision: int = Field(ge=0)


class FeedbackRequest(DTO):
    event_id: str = Field(min_length=1,max_length=100)
    status: str = Field(pattern='^(RENDERED|FAILED)$')
    error_code: str | None = Field(default=None,max_length=100)


def install_agent(app, runtime, store, *, initialize_model=True, recovery_interval=5,
                  maintenance_interval=60, include_home=True):
    from .agent_lifecycle import AgentLifecycle
    lifecycle = AgentLifecycle(runtime, store, initialize_model=initialize_model,
        recovery_interval=recovery_interval, maintenance_interval=maintenance_interval)
    router = APIRouter(lifespan=lifecycle.lifespan)
    app.state.agent = lifecycle
    from journeyplus.product.knowledge_api import knowledge_router
    app.include_router(knowledge_router(store.factory))
    @app.api_route('/v1/agent/{path:path}',methods=['POST','PUT','PATCH','DELETE'])
    def retired_v1(path:str):
        from journeyplus.product.knowledge_api import retired_response
        return retired_response()
    static=Path(__file__).with_name('static')
    app.mount('/assets',StaticFiles(directory=static),name='assets')

    from sqlalchemy.exc import SQLAlchemyError
    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(TimeoutError)
    async def unavailable_storage(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503,content={'code':'DATABASE_UNAVAILABLE'})

    @app.exception_handler(StoreError)
    async def store_error(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=error.status,content={'code':error.code})

    @app.exception_handler(LookupError)
    async def missing_reference(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404,content={'code':'REFERENCE_NOT_FOUND'})

    @app.exception_handler(ValueError)
    async def invalid_reference(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422,content={'code':'INVALID_REQUEST'})

    @app.get('/workspace',response_class=HTMLResponse)
    def workspace_page():return (static/'workspace_v3.html').read_text()

    @app.get('/knowledge',response_class=HTMLResponse)
    def knowledge_page():return (static/'knowledge.html').read_text()

    @router.post('/v3/agent/workspaces')
    def create(request:CreateRequest):
        if request.import_workspace_id:
            return store.import_workspace(str(request.import_workspace_id))
        return store.create()

    @router.get('/v3/agent/workspaces/{workspace_id}')
    def read(workspace_id:UUID,cursor:str|None=None,limit:int=Query(50,ge=1,le=100)):
        return store.read(str(workspace_id),cursor,limit)

    @router.post('/v3/agent/workspaces/{workspace_id}/runs',status_code=202)
    async def start(workspace_id:UUID,request:RunRequest):
        if lifecycle.status != 'READY':
            raise HTTPException(503, {'code': 'AGENT_' + lifecycle.status})
        result=await blocking_call(store.start,str(workspace_id),**request.model_dump())
        lifecycle.dispatch(result['run_id'])
        return result

    @router.get('/v3/agent/workspaces/{workspace_id}/runs/{run_id}/events')
    def events(workspace_id:UUID,run_id:UUID,after:int=0):
        store.events(str(workspace_id),str(run_id),after)
        async def stream():
            sequence=after
            while True:
                items,status=await blocking_call(store.events,str(workspace_id),str(run_id),sequence)
                for item in items:
                    sequence=item['seq']
                    yield f"id: {sequence}\ndata: {json.dumps(item,ensure_ascii=False)}\n\n"
                if status in TERMINAL:return
                yield ': heartbeat\n\n'
                await asyncio.sleep(.25)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @router.post('/v3/agent/workspaces/{workspace_id}/runs/{run_id}/cancel')
    async def cancel(workspace_id:UUID,run_id:UUID,request:CancelRequest):
        await blocking_call(store.events,str(workspace_id),str(run_id))
        await runtime.cancel(str(run_id))
        status=(await blocking_call(store.events,str(workspace_id),str(run_id)))[1]
        return {'status':status if status in TERMINAL else 'CANCEL_REQUESTED','completed_operations':await blocking_call(store.completed_operations,str(run_id))}

    @router.post('/v3/agent/workspaces/{workspace_id}/focus')
    def focus(workspace_id:UUID,request:FocusRequest):
        return store.focus(str(workspace_id),**request.model_dump())

    @router.get('/v3/agent/workspaces/{workspace_id}/artifacts/{artifact_id}')
    def artifact(workspace_id:UUID,artifact_id:UUID):
        try:return store.artifacts.read(str(workspace_id),'artifact:'+str(artifact_id))
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @router.post('/v3/agent/workspaces/{workspace_id}/presentations/{presentation_id}/browse')
    def browse(workspace_id:UUID,presentation_id:UUID,request:BrowseRequest):
        return store.browse(str(workspace_id),'artifact:'+str(presentation_id),**request.model_dump())

    @router.post('/v3/agent/workspaces/{workspace_id}/presentations/{presentation_id}/feedback')
    def feedback(workspace_id:UUID,presentation_id:UUID,request:FeedbackRequest):
        return store.feedback(str(workspace_id),'artifact:'+str(presentation_id),**request.model_dump())

    from .knowledge_public_api import public_knowledge_router
    app.include_router(public_knowledge_router(knowledge=runtime.services['knowledge']))
    @app.get('/explore',response_class=HTMLResponse)
    def explore_page():return (static/'explore.html').read_text()
    if include_home:
        @app.get('/',response_class=HTMLResponse)
        def home_page():return (static/'knowledge.html').read_text()
    @router.get('/v3/agent/status')
    def availability():
        knowledge=runtime.services['knowledge'].availability()
        return {'status': lifecycle.status, 'error_type': lifecycle.error,
                'knowledge':knowledge,'ready_for_route_queries':lifecycle.status=='READY' and knowledge['status']=='AVAILABLE'}

    app.include_router(router)
    return app


def create_agent_app(runtime, store, **options):
    app = FastAPI(title='JourneyPlus Agent')
    return install_agent(app, runtime, store, **options)
