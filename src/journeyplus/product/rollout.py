"""One consumer switch with an explicit maintenance/rollback write fence."""
from fastapi.responses import JSONResponse,RedirectResponse


def install_rollout(app,mode='legacy',user_writes_paused=False):
    mode=mode.casefold()
    if mode not in {'legacy','unified','rollback'}:raise ValueError('Invalid knowledge read mode')
    paused=user_writes_paused or mode=='rollback'
    entries={'/':'/knowledge','/agent':'/workspace','/matches':'/explore','/briefs':'/knowledge'}
    legacy_business=('/v1/agent','/v1/personalized-matches','/v1/briefs','/v1/match-opportunities')

    @app.middleware('http')
    async def consumer_boundary(request,call_next):
        path=request.url.path
        user_mutation=(path.startswith('/v1/status-holdings') or path.startswith('/v2/wait-goal')
                       or (path.startswith('/v2/agent/workspaces/') and path.endswith(('/confirm','/messages'))))
        if paused and request.method not in {'GET','HEAD','OPTIONS'} and user_mutation:
            return JSONResponse({'detail':'系统维护中，暂不接受会籍或等待任务变更；已有记录保留。','code':'USER_WRITES_PAUSED'},status_code=503)
        if mode!='legacy' and path.startswith(legacy_business):
            return JSONResponse({'detail':'此旧版读取入口已停止使用，请从当前页面重新进入。','code':'LEGACY_CONSUMER_DISABLED'},status_code=409)
        if mode=='rollback' and (path=='/v2/routes/query' or path.endswith(('/routes/explore','/routes/browse','/messages'))):
            return JSONResponse({'detail':'路径推荐暂时停用，已发布活动资料仍可浏览。','code':'RECOMMENDATIONS_PAUSED'},status_code=503)
        if request.method in {'GET','HEAD'} and mode!='legacy' and path in entries:
            target='/knowledge' if mode=='rollback' else entries[path]
            return RedirectResponse(target,status_code=307)
        if request.method in {'GET','HEAD'} and mode!='legacy' and path.startswith('/opportunities/'):
            from uuid import UUID
            try:identity=UUID(path.removeprefix('/opportunities/'))
            except ValueError:return JSONResponse({'detail':'历史活动标识无效。'},status_code=404)
            return RedirectResponse('/knowledge?legacy_opportunity='+str(identity),status_code=307)
        response=await call_next(request)
        response.headers['X-JourneyPlus-Read-Mode']=mode
        return response

    @app.get('/v2/rollout')
    def rollout_status():
        return {'mode':mode,'user_writes_paused':paused,'recommendations_enabled':mode!='rollback'}
