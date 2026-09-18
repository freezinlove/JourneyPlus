import httpx
import pytest
from journeyplus.sources.base import FetchResponse
from journeyplus.statusmatch.transport import StatusMatchBatchFetcher, is_challenge

URL='https://flyingblue.statusmatch.com/'
NORMAL=FetchResponse('<html><title>Offer</title><p>Gold $99</p></html>', 'text/html', URL)
CHALLENGE=FetchResponse('<title>Just a moment...</title>', 'text/html', URL)

class Fake:
    def __init__(self, *responses):
        self.responses=list(responses)
        self.calls=[]
        self.closed=False
    def get(self, url):
        self.calls.append(url)
        r=self.responses.pop(0)
        if isinstance(r,Exception): raise r
        return r
    def close(self): self.closed=True

@pytest.mark.parametrize('successes',[0,2])
def test_sticky_switch_and_new_batch(successes):
    http=Fake(*([NORMAL]*successes),CHALLENGE)
    browser=Fake(NORMAL,NORMAL)
    batch=StatusMatchBatchFetcher(http=http,browser_factory=lambda:browser)
    for _ in range(successes+2): assert batch.get(URL)==NORMAL
    assert len(http.calls)==successes+1
    assert len(browser.calls)==2
    batch.close()
    assert http.closed and browser.closed
    fresh=StatusMatchBatchFetcher(http=Fake(NORMAL),browser_factory=lambda:pytest.fail('browser started'))
    assert fresh.get(URL)==NORMAL
    assert not fresh.browser_mode

@pytest.mark.parametrize('status',[403,404,500])
def test_non_challenge_http_error_does_not_switch(status):
    response=httpx.Response(status,request=httpx.Request('GET',URL),text='ordinary error')
    error=httpx.HTTPStatusError('failure',request=response.request,response=response)
    batch=StatusMatchBatchFetcher(http=Fake(error))
    with pytest.raises(httpx.HTTPStatusError): batch.get(URL)
    assert not batch.browser_mode

def test_header_challenge_switches():
    response=httpx.Response(403,request=httpx.Request('GET',URL),headers={'cf-mitigated':'challenge'})
    error=httpx.HTTPStatusError('failure',request=response.request,response=response)
    batch=StatusMatchBatchFetcher(http=Fake(error),browser_factory=lambda:Fake(NORMAL))
    assert batch.get(URL)==NORMAL

def test_browser_challenge_fails_and_closes():
    browser=Fake(CHALLENGE)
    batch=StatusMatchBatchFetcher(http=Fake(CHALLENGE),browser_factory=lambda:browser)
    try:
        with pytest.raises(ValueError,match='challenge'): batch.get(URL)
    finally: batch.close()
    assert browser.closed

def test_scripts_are_not_challenges():
    assert not is_challenge('<title>Offer</title><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>')

def test_timeout_does_not_switch():
    batch=StatusMatchBatchFetcher(http=Fake(httpx.ReadTimeout('timeout')))
    with pytest.raises(httpx.ReadTimeout): batch.get(URL)
    assert not batch.browser_mode

def test_header_challenge_on_200():
    challenge=FetchResponse('<html></html>','text/html',URL,{'cf-mitigated':'challenge'})
    batch=StatusMatchBatchFetcher(http=Fake(challenge),browser_factory=lambda:Fake(NORMAL))
    assert batch.get(URL)==NORMAL
    assert batch.browser_mode

def test_daily_phases_share_and_close_default_batch(session_factory, monkeypatch):
    from journeyplus.automation.service import run_daily_cycle
    from journeyplus.ai.provider import SequenceAIProvider
    from journeyplus.statusmatch.service import StatusMatchMonitoringSummary
    from journeyplus.automation import service
    import journeyplus.statusmatch.transport as transport
    import journeyplus.statusmatch.monitoring as monitoring
    import journeyplus.statusmatch.articles as articles
    batches=[]
    seen=[]
    def factory():
        batch=StatusMatchBatchFetcher(http=Fake(CHALLENGE),browser_factory=lambda:Fake(NORMAL,NORMAL))
        batches.append(batch)
        return batch
    def monitor(_, fetcher, **kwargs):
        seen.append(fetcher)
        fetcher.get(URL)
        return StatusMatchMonitoringSummary()
    def prepare(_, fetcher, **kwargs):
        seen.append(fetcher)
        assert fetcher.browser_mode
        fetcher.get(URL)
        return service.ArticleProjectPreparationSummary()
    monkeypatch.setattr(transport,'StatusMatchBatchFetcher',factory)
    monkeypatch.setattr(monitoring,'monitor_statusmatch_projects',monitor)
    monkeypatch.setattr(articles,'prepare_article_projects_in_phases',prepare)
    run_daily_cycle(session_factory,SequenceAIProvider([]),lambda _: None,source_ids=[])
    assert len(seen)==2 and seen[0] is seen[1]
    assert batches[0].http.closed and batches[0].browser.closed

def test_mail_discovered_pages_use_shared_batch():
    from journeyplus.sources.gmail import GmailStatusServicesAdapter
    from journeyplus.statusmatch.transport import bind_batch_adapter_factory
    adapter=GmailStatusServicesAdapter(object(),project_fetcher=Fake())
    batch=StatusMatchBatchFetcher(http=Fake(CHALLENGE),browser_factory=lambda:Fake(NORMAL))
    factory=bind_batch_adapter_factory(lambda _:adapter,batch)
    assert factory('status_services_mail')._project_fetcher is batch

def test_browser_selects_completed_normal_document_not_challenge_or_dom():
    from types import SimpleNamespace
    from journeyplus.statusmatch.transport import ChromiumFetcher
    class Page:
        main_frame=object()
        closed=False
        def route(self,*args): pass
        def on(self,event,callback): self.finished=callback
        def goto(self,*args,**kwargs):
            self.finished(SimpleNamespace(is_navigation_request=lambda:False,
                response=lambda:pytest.fail('Subresource response must not be read')))
            for status,body in [(403,CHALLENGE.body),(200,NORMAL.body)]:
                request=SimpleNamespace(is_navigation_request=lambda:True,frame=self.main_frame)
                response=SimpleNamespace(request=request,frame=self.main_frame,status=status,
                    headers={'content-type':'text/html; charset=utf-8'},url=URL,text=lambda body=body:body)
                request.response=lambda response=response:response
                self.finished(request)
        def remove_listener(self,event,callback):
            assert callback is self.finished
            self.finished=None
        def content(self): pytest.fail('Rendered DOM must not be used')
        def close(self): self.closed=True
    page=Page()
    browser=ChromiumFetcher()
    browser._context=SimpleNamespace(new_page=lambda:page)
    result=browser.get(URL)
    assert result.body==NORMAL.body
    assert result.content_type=='text/html'
    assert page.closed
