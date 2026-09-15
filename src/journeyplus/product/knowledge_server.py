"""Independent published-knowledge UI; does not construct an AI provider or Agent."""
from argparse import ArgumentParser
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from .knowledge_public_api import public_knowledge_router


def create_knowledge_app(factory,*,agent_url=None):
    app=FastAPI(title='JourneyPlus Knowledge')
    from .auth import install_auth
    install_auth(app,factory,landing='/knowledge')
    static=Path(__file__).with_name('static')
    app.mount('/assets',StaticFiles(directory=static),name='assets')
    app.include_router(public_knowledge_router(factory))
    def page(name):
        import html,re
        content=(static/name).read_text()
        if agent_url:
            if not agent_url.startswith(('http://','https://','/')):raise ValueError('Invalid Agent UI URL')
            return content.replace('href="/workspace"','href="'+html.escape(agent_url,quote=True)+'"')
        return re.sub(r'<a[^>]*href="/workspace"[^>]*>.*?</a>','',content)
    @app.get('/',response_class=HTMLResponse)
    @app.get('/knowledge',response_class=HTMLResponse)
    def knowledge():return page('knowledge.html')
    @app.get('/explore',response_class=HTMLResponse)
    def explore():return page('explore.html')
    return app


def main():
    parser=ArgumentParser();parser.add_argument('--port',type=int,default=8014);args=parser.parse_args()
    import uvicorn
    factory=sessionmaker(create_engine(Settings.from_env().database_url),expire_on_commit=False)
    uvicorn.run(create_knowledge_app(factory),host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
