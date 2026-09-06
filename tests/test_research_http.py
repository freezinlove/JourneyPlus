import httpx
import pytest
from journeyplus.agent.research_http import ResearchBudget,ResearchBudgetExceeded,read_research_html


def test_external_redirect_is_rejected_before_following_even_with_auto_redirect_client():
    urls=[]
    def response(request):
        urls.append(str(request.url))
        return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
    with httpx.Client(follow_redirects=True,transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ValueError,match='NOT_ALLOWED'):
            read_research_html(client,'/company/example',ResearchBudget())
    assert urls==['https://statusmatcher.com/company/example']


def test_redirect_hops_consume_the_same_request_budget():
    urls=[]
    def response(request):
        urls.append(str(request.url))
        return httpx.Response(302,headers={'location':'/company/next'})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        budget=ResearchBudget(max_requests=2)
        with pytest.raises(ResearchBudgetExceeded,match='REQUEST_LIMIT'):
            read_research_html(client,'/company/example',budget)
    assert len(urls)==2 and budget.requests==2


def test_total_byte_budget_is_shared_across_pages_and_expired_budget_reads_nothing():
    urls=[]
    def response(request):urls.append(str(request.url));return httpx.Response(200,text='x'*60)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        budget=ResearchBudget(max_bytes=100)
        assert len(read_research_html(client,'/company/example',budget)[0])==60
        with pytest.raises(ResearchBudgetExceeded,match='TOTAL_BYTES'):
            read_research_html(client,'/report/123',budget)
        with pytest.raises(ResearchBudgetExceeded,match='DEADLINE'):
            read_research_html(client,'/company/example',ResearchBudget(duration_seconds=0))
    assert len(urls)==2


def test_response_limit_and_429_have_no_implicit_retries():
    calls=[]
    def response(request):calls.append(request);return httpx.Response(200,text='x'*100)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ResearchBudgetExceeded,match='RESPONSE_LIMIT'):
            read_research_html(client,'/company/example',ResearchBudget(),response_limit=50)
    assert len(calls)==1
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429))) as client:
        budget=ResearchBudget()
        with pytest.raises(httpx.HTTPStatusError):read_research_html(client,'/company/example',budget)
        assert budget.requests==1
