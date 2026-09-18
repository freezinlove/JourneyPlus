"""Authentication boundary shared by the Agent and product HTTP surfaces."""
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
import os
import re
import secrets
from sqlalchemy import select,delete
from fastapi import Request
from fastapi.responses import JSONResponse,RedirectResponse,HTMLResponse
from pydantic import BaseModel,Field
from journeyplus.accounts import UserAccount,LoginSession,verify_password,token_hash
from journeyplus.models import now_utc
from journeyplus.user_scope import acting_as
from journeyplus.agent.adapters.artifacts import aware

COOKIE='journeyplus_session'

class LoginInput(BaseModel):
    username:str=Field(min_length=1,max_length=100)
    password:str=Field(min_length=1,max_length=512)


def install_auth(app,factory,*,landing='/workspace'):
    import journeyplus.user_isolation
    cookie_name = os.getenv("JOURNEYPLUS_SESSION_COOKIE_NAME", COOKIE)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cookie_name):
        raise ValueError("JOURNEYPLUS_SESSION_COOKIE_NAME must be a nonempty cookie name")
    app.state.session_cookie_name = cookie_name
    @app.middleware('http')
    async def authenticate(request:Request,call_next):
        path=request.url.path
        public=path in {'/login','/auth/login'} or path.startswith('/assets/')
        # Cookie-authenticated writes are same-origin. JSON clients without Origin
        # remain supported; cross-site form submissions cannot call JSON endpoints.
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin')
            if request.headers.get('sec-fetch-site')=='cross-site' or (origin and urlsplit(origin).netloc!=request.headers.get('host')):
                return JSONResponse({'code':'ORIGIN_DENIED'},status_code=403)
        if public:
            response=await call_next(request)
            if path.startswith('/assets/'):
                response.headers['Cache-Control']='no-cache'
            return response
        token=request.cookies.get(cookie_name,'')
        def identify():
            with factory() as s:
                login=s.get(LoginSession,token_hash(token)) if token else None
                if login is None or aware(login.expires_at)<=now_utc():return None
                user=s.get(UserAccount,login.user_id)
                return user.id if user else None
        from journeyplus.agent.harness.execution import blocking_call
        identity=await blocking_call(identify)
        if identity is None:
            if path.startswith(('/v1/','/v2/','/v3/','/auth/')):return JSONResponse({'code':'LOGIN_REQUIRED'},status_code=401)
            return RedirectResponse('/login',status_code=303)
        import re
        matched=re.match(r'^/v3/agent/workspaces/([0-9a-fA-F-]{36})(?:/|$)',path)
        if matched:
            from uuid import UUID
            def owns():
                from journeyplus.models import AgentInteraction
                with factory() as s:
                    account=s.get(UserAccount,identity)
                    row=s.get(AgentInteraction,UUID(matched.group(1)))
                    if row is None or row.user_id!=identity:return 404
                    if account.current_workspace_id!=row.id or aware(row.expires_at)<=now_utc():return 410
            with acting_as(identity):denied=await blocking_call(owns)
            if denied:return JSONResponse({'code':'WORKSPACE_NOT_FOUND' if denied==404 else 'WORKSPACE_EXPIRED'},status_code=denied)
        if path.startswith('/v2/agent/') or path=='/v1/agent/state':
            return JSONResponse({'code':'AGENT_RUNTIME_RETIRED'},status_code=410)
        request.state.user_id=identity
        with acting_as(identity):
            response=await call_next(request)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get('/login',response_class=HTMLResponse)
    def login_page():
        import json
        return (Path(__file__).with_name('static')/'login.html').read_text().replace('"__LOGIN_LANDING__"',json.dumps(landing))

    @app.post('/auth/login')
    def login(body:LoginInput,request:Request):
        token=secrets.token_urlsafe(32)
        with factory.begin() as s:
            user=s.scalar(select(UserAccount).where(UserAccount.username==body.username.strip().casefold()).with_for_update())
            valid=user and (user.locked_until is None or aware(user.locked_until)<=now_utc()) and verify_password(body.password,user.password_hash)
            if not valid:
                if user:
                    user.failed_logins+=1
                    if user.failed_logins>=10:user.locked_until=now_utc()+timedelta(minutes=5)
                response=JSONResponse({'code':'INVALID_LOGIN','message':'账号或密码不正确，或请稍后重试。'},status_code=401)
            else:
                user.failed_logins=0;user.locked_until=None
                old=request.cookies.get(cookie_name)
                if old:s.execute(delete(LoginSession).where(LoginSession.token_hash==token_hash(old)))
                s.add(LoginSession(token_hash=token_hash(token),user_id=user.id,expires_at=now_utc()+timedelta(days=30)))
                response=JSONResponse({'username':user.username})
                response.set_cookie(cookie_name,token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=30*86400,path='/')
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/auth/me')
    def me(request:Request):
        with factory() as s:
            user=s.get(UserAccount,request.state.user_id)
            return JSONResponse({'id':str(user.id),'username':user.username},headers={'Cache-Control':'no-store'})

    @app.post('/auth/logout')
    def logout(request:Request):
        with factory.begin() as s:
            s.execute(delete(LoginSession).where(LoginSession.token_hash==token_hash(request.cookies.get(cookie_name,''))))
        response=JSONResponse({'ok':True});response.delete_cookie(cookie_name,path='/')
        return response
