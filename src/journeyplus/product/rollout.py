"""Current AIWorkflow consumer boundary and independent write maintenance flag."""
from fastapi.responses import JSONResponse


def configure_user_writes(factory, paused=False):
    factory.configure(info={**factory.kw.get('info', {}),
        'user_business_journal':False, 'user_business_writes_paused':paused})


def install_rollout(app, user_writes_paused=False):
    @app.middleware('http')
    async def consumer_boundary(request, call_next):
        path = request.url.path
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if path.startswith(('/v1/agent/','/v2/agent/','/v2/wait-goal')):
                from journeyplus.product.knowledge_api import retired_response
                return retired_response()
            if user_writes_paused and path.startswith('/v1/status-holdings'):
                return JSONResponse({'detail':'系统维护中，暂不接受会籍或等待任务变更；已有记录保留。',
                    'code':'USER_WRITES_PAUSED'}, status_code=503)
        response = await call_next(request)
        response.headers['X-JourneyPlus-Read-Mode'] = 'aiworkflow'
        return response

    @app.get('/v2/rollout')
    def rollout_status():
        return {'mode':'aiworkflow', 'user_writes_paused':user_writes_paused,
                'recommendations_enabled':True}
