from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from journeyplus.product.web_frontend import install_web_frontend


def test_web_entry_and_legacy_routes(tmp_path):
    (tmp_path / 'assets/web').mkdir(parents=True)
    (tmp_path / 'assets/web/app.js').write_text('real-client')
    (tmp_path / 'index.html').write_text('<div id="root">new-web</div>')
    app = FastAPI()
    @app.get('/workspace', response_class=HTMLResponse)
    def old(): return 'old-web'
    @app.get('/v1/example')
    def api(): return {'real': True}
    install_web_frontend(app, tmp_path)
    with TestClient(app) as client:
        for path in ['/', '/login', '/workspace', '/holdings', '/news', '/briefs', '/knowledge']:
            response = client.get(path)
            assert 'new-web' in response.text
            assert response.headers['cache-control'] == 'no-store'
        assert client.get('/legacy/workspace').text == 'old-web'
        assert client.get('/assets/web/app.js').text == 'real-client'
        assert client.get('/v1/example').json() == {'real': True}
        response = client.get('/opportunities/example?version_ref=historical', follow_redirects=False)
        assert response.headers['location'] == '/news?version_ref=historical&activity_id=example'
        assert client.get('/v3/missing').status_code == 404


def test_missing_build_leaves_api_installation_unchanged(tmp_path):
    app = FastAPI()
    before = list(app.routes)
    install_web_frontend(app, tmp_path)
    assert app.routes == before
