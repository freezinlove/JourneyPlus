"""Serve the independently built Web client; leave API and Agent routes intact."""
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount


def install_web_frontend(app, dist: Path | None = None):
    if os.getenv('JOURNEYPLUS_WEB_FRONTEND') == 'legacy':
        return
    dist = dist or Path(os.getenv('JOURNEYPLUS_WEB_DIST', str(
        Path(__file__).resolve().parents[3] / 'clients/web/dist')))
    if not (dist / 'index.html').is_file():
        return  # API-only installations can continue using the original pages.
    pages = {'/', '/login', '/workspace', '/knowledge', '/holdings', '/briefs', '/opportunities/{opportunity_id}'}
    for route in list(app.router.routes):
        if getattr(route, 'path', None) in pages:
            app.add_api_route('/legacy' + route.path, route.endpoint,
                             methods=['GET'], response_class=route.response_class,
                             include_in_schema=False)
            app.router.routes.remove(route)
    # More specific than the original /assets mount, whose files remain available.
    app.router.routes.insert(0, Mount('/assets/web',
        app=StaticFiles(directory=dist / 'assets/web'), name='web-assets'))

    def index():
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-store'})

    for path in ['/', '/login', '/workspace', '/knowledge', '/holdings', '/briefs', '/news']:
        app.add_api_route(path, index, methods=['GET'], include_in_schema=False)

    @app.get('/opportunities/{opportunity_id}', include_in_schema=False)
    def opportunity(opportunity_id: str, request: Request):
        from urllib.parse import urlencode
        params = dict(request.query_params)
        params['activity_id'] = opportunity_id
        return RedirectResponse('/news?' + urlencode(params), status_code=307)
