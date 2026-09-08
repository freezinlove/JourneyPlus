"""Independent v3 transport. No user-language parsing or workflow imports."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from sqlalchemy import select
from journeyplus.agent.harness.contracts import DTO
from journeyplus.agent.adapters.persistence import StoreError, TERMINAL
from journeyplus.agent.adapters.models import RunCheckpoint


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


def create_agent_app(runtime,store,*,initialize_model=True,recovery_interval=5,maintenance_interval=60,include_home=True):
    workers={}
    def dispatch(run_id):
        if run_id not in workers or workers[run_id].done():
            workers[run_id]=asyncio.create_task(runtime.run(run_id))

    async def recover_pending():
        while True:
            try:
                with store.factory() as s:
                    from journeyplus.models import AgentInteraction,now_utc
                    pending=list(s.scalars(select(RunCheckpoint.run_id).join(AgentInteraction,AgentInteraction.id==RunCheckpoint.workspace_id).where(RunCheckpoint.phase.not_in(TERMINAL),AgentInteraction.expires_at>now_utc())))
                for identity in pending:dispatch(str(identity))
                for identity in list(workers):
                    if workers[identity].done():
                        task=workers.pop(identity)
                        if not task.cancelled():task.exception()
            except Exception as error:
                logging.getLogger(__name__).warning('Recovery scan failed: %s',type(error).__name__)
            await asyncio.sleep(recovery_interval)

    async def maintain():
        while True:
            try:
                callback=runtime.services.get('maintenance')
                if callback:await asyncio.to_thread(callback)
            except Exception as error:
                logging.getLogger(__name__).warning('Agent maintenance failed: %s',type(error).__name__)
            await asyncio.sleep(maintenance_interval)

    @asynccontextmanager
    async def lifespan(app):
        if initialize_model:await runtime.ports.model.initialize()
        research=runtime.services.get('research')
        if research and research.enabled and research.search_backend:await research.search_backend.initialize()
        recovery=asyncio.create_task(recover_pending())
        maintenance=asyncio.create_task(maintain())
        try:yield
        finally:
            recovery.cancel()
            maintenance.cancel()
            await asyncio.gather(recovery,maintenance,return_exceptions=True)
            for identity in list(workers):
                if not workers[identity].done():runtime.cancel(identity)
            if workers:await asyncio.gather(*workers.values(),return_exceptions=True)
            if hasattr(runtime.ports.model,'close'):await runtime.ports.model.close()
            if runtime.services.get('research'):await runtime.services['research'].close()
    app=FastAPI(title='JourneyPlus Agent',lifespan=lifespan)
    from journeyplus.product.knowledge_api import knowledge_router
    app.include_router(knowledge_router(store.factory))
    @app.api_route('/v1/agent/{path:path}',methods=['POST','PUT','PATCH','DELETE'])
    def retired_v1(path:str):
        from journeyplus.product.knowledge_api import retired_response
        return retired_response()
    static=Path(__file__).with_name('static')
    app.mount('/assets',StaticFiles(directory=static),name='assets')

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

    @app.post('/v3/agent/workspaces')
    def create(request:CreateRequest):
        if request.import_workspace_id:
            return store.import_workspace(str(request.import_workspace_id))
        return store.create()

    @app.get('/v3/agent/workspaces/{workspace_id}')
    def read(workspace_id:UUID,cursor:str|None=None,limit:int=Query(50,ge=1,le=100)):
        return store.read(str(workspace_id),cursor,limit)

    @app.post('/v3/agent/workspaces/{workspace_id}/runs',status_code=202)
    async def start(workspace_id:UUID,request:RunRequest):
        result=store.start(str(workspace_id),**request.model_dump())
        dispatch(result['run_id'])
        return result

    @app.get('/v3/agent/workspaces/{workspace_id}/runs/{run_id}/events')
    def events(workspace_id:UUID,run_id:UUID,after:int=0):
        store.events(str(workspace_id),str(run_id),after)
        async def stream():
            sequence=after
            while True:
                items,status=store.events(str(workspace_id),str(run_id),sequence)
                for item in items:
                    sequence=item['seq']
                    yield f"id: {sequence}\ndata: {json.dumps(item,ensure_ascii=False)}\n\n"
                if status in TERMINAL:return
                yield ': heartbeat\n\n'
                await asyncio.sleep(.25)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @app.post('/v3/agent/workspaces/{workspace_id}/runs/{run_id}/cancel')
    def cancel(workspace_id:UUID,run_id:UUID,request:CancelRequest):
        store.events(str(workspace_id),str(run_id))
        runtime.cancel(str(run_id))
        status=store.events(str(workspace_id),str(run_id))[1]
        return {'status':status if status in TERMINAL else 'CANCEL_REQUESTED','completed_operations':store.completed_operations(str(run_id))}

    @app.post('/v3/agent/workspaces/{workspace_id}/focus')
    def focus(workspace_id:UUID,request:FocusRequest):
        return store.focus(str(workspace_id),**request.model_dump())

    @app.get('/v3/agent/workspaces/{workspace_id}/artifacts/{artifact_id}')
    def artifact(workspace_id:UUID,artifact_id:UUID):
        try:return store.artifacts.read(str(workspace_id),'artifact:'+str(artifact_id))
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc

    @app.post('/v3/agent/workspaces/{workspace_id}/presentations/{presentation_id}/browse')
    def browse(workspace_id:UUID,presentation_id:UUID,request:BrowseRequest):
        return store.browse(str(workspace_id),'artifact:'+str(presentation_id),**request.model_dump())

    @app.post('/v3/agent/workspaces/{workspace_id}/presentations/{presentation_id}/feedback')
    def feedback(workspace_id:UUID,presentation_id:UUID,request:FeedbackRequest):
        return store.feedback(str(workspace_id),'artifact:'+str(presentation_id),**request.model_dump())

    from .knowledge_public_api import public_knowledge_router
    app.include_router(public_knowledge_router(knowledge=runtime.services['knowledge']))
    @app.get('/explore',response_class=HTMLResponse)
    def explore_page():return (static/'explore.html').read_text()
    if include_home:
        @app.get('/',response_class=HTMLResponse)
        def home_page():return (static/'knowledge.html').read_text()
    return app
