import asyncio,socket
import httpx
import pytest
from journeyplus.agent.services.research import PublicResearch
from journeyplus.agent.tools.contracts import SearchInput
from journeyplus.agent.adapters import models as runtime_models  # Register tables before the DB fixture runs.


def test_public_reader_pins_dns_preserves_cache_timestamp_and_refreshes(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda host,port,*args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1' if host=='localhost' else '93.184.216.34',443))])
    async def scenario():
        seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,text='<html><title>Example</title><body>'+('text '*500)+'</body></html>')
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond));reader=PublicResearch(True,client)
        first=await reader.page('https://example.org/',max_chars=1000)
        cached=await reader.page('https://example.org/',max_chars=10000)
        assert first['truncated'] and not cached['truncated']
        assert cached['cache_hit'] and cached['observed_at']==first['observed_at'] and len(seen)==1
        fresh=await reader.page('https://example.org/',refresh=True)
        assert len(seen)==2 and not fresh['cache_hit']
        assert seen[0].url.host=='93.184.216.34' and seen[0].headers['host']=='example.org'
        assert seen[0].extensions['sni_hostname']=='example.org'
        with pytest.raises(ValueError):await reader.page('https://localhost/')
        assert len(seen)==2
        await reader.close()
    asyncio.run(scenario())


def test_search_cursor_is_bound_to_query_and_original_results():
    async def scenario():
        reader=PublicResearch(True)
        from time import monotonic
        reader.searches['snapshot']=('incorrect-query',monotonic(),[])
        with pytest.raises(ValueError):await reader.search(SearchInput(query='another',cursor='snapshot|1'))
        await reader.close()
    asyncio.run(scenario())


def test_large_page_artifact_keeps_bounded_prefix_and_truncation_on_cache(monkeypatch):
    import json
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    async def scenario():
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='<html><body>'+('"文本\\'*300000)+'</body></html>')))
        reader=PublicResearch(True,client)
        first=await reader.page('https://example.org/large',max_chars=30000)
        assert first['raw_truncated'] and first['truncated']
        assert len(json.dumps(first,ensure_ascii=False).encode())<1_000_000
        assert first['retained_raw_bytes']==len(first['raw_html'].encode())
        assert first['content_hash_scope']=='retained_download_prefix'
        cached=await reader.page('https://example.org/large',max_chars=1_000_000)
        assert cached['truncated'] and cached['cache_hit']
        await reader.close()
    asyncio.run(scenario())


def test_page_sections_use_actual_headings_and_report_missing_or_truncated_text():
    from journeyplus.agent.services.page_sections import select_sections
    html='<h1>Offer</h1><p>Overview</p><h2>Terms</h2><p>Only once per person.</p><h2>Fees</h2><p>USD 49</p><script>ignore</script>'
    selected=select_sections(html,['terms'],1000)
    assert selected['text']=='Only once per person.' and selected['missing_sections']==[]
    assert select_sections(html,['absent'],1000)['missing_sections']==['absent']
    assert select_sections(html,['Terms'],5)['truncated'] is True
    assert 'USD 49' not in selected['text']


def test_web_tool_paginates_original_text_and_links_without_refetch(session_factory):
    from tests.test_harness_tools import context
    from journeyplus.agent.tools.research import read
    from journeyplus.agent.tools.contracts import WebReadInput
    from journeyplus.agent.harness.context import bounded_result
    import hashlib
    body='条件不能省略。'*1800+'最终资格仍然未知。'
    links=[{'url':f'https://example.org/report/{i}','title':f'Report {i}'} for i in range(100)]
    class Reader:
        calls=0
        async def page(self,*args):
            self.calls+=1
            return {'url':'https://example.org/','final_url':'https://example.org/','title':'Original terms',
                    'raw_html':'<html><body>'+body+'</body></html>','text':body[:1000],
                    'links':links,'observed_at':'2026-09-08T00:00:00Z','cache_hit':False,
                    'content_hash':hashlib.sha256(body.encode()).hexdigest(),'raw_truncated':False}
    async def scenario():
        runtime,store,w,ctx=context(session_factory)
        await runtime.services['research'].close()
        reader=Reader();ctx.services['research']=reader
        args=WebReadInput(url='https://example.org/',max_chars=10000)
        first=await read(args,ctx);current=first;text_parts=[];all_links=[]
        assert first.status=='PARTIAL' and first.data['text'] and first.next_cursor
        while True:
            text_parts.append(current.data['text']);all_links+=current.data['links']
            if not current.next_cursor:break
            current=await read(args.model_copy(update={'cursor':current.next_cursor}),ctx)
        assert ''.join(text_parts)==body and all_links==links and reader.calls==1
        assert current.coverage['complete'] and current.status=='OK'
        with pytest.raises(ValueError):
            await read(WebReadInput(url='https://example.org/changed',cursor=first.next_cursor),ctx)
        with pytest.raises(ValueError):
            WebReadInput(url=args.url,cursor=first.next_cursor,refresh=True)
    asyncio.run(scenario())


def test_form_options_are_explicitly_expandable_and_not_article_evidence():
    from journeyplus.agent.services.web_projection import page_excerpt
    from journeyplus.agent.tools.contracts import WebReadInput
    page={'url':'https://example.org/','raw_html':'<html><body><h1>Reports</h1><p>No submitted report here.</p><select name="source"><option>Example Airline</option></select></body></html>',
          'links':[]}
    args=WebReadInput(url=page['url'])
    article,coverage,_=page_excerpt(page,'artifact:page',args)
    assert 'Example Airline' not in article['text']
    assert article['form_controls'][0]['name']=='source' and coverage['form_control_count']==1
    expanded,_,_=page_excerpt(page,'artifact:page',args.model_copy(update={'include_controls':True}))
    assert 'Example Airline' in expanded['text']
    assert expanded['content_scope']=='page_text_including_form_options'
    assert article['evidence_scope']['authority']=='not_verified'


def test_discovery_coverage_distinguishes_link_paging_from_report_reads(session_factory):
    from tests.test_harness_tools import context
    from journeyplus.agent.tools.research import search
    results=[{'url':f'https://example.org/{i}','title':str(i)} for i in range(3)]
    class Reader:
        async def search(self,args):
            return PublicResearch._search_page(results,'snapshot',int(args.cursor or 0),2)
    async def scenario():
        runtime,store,w,ctx=context(session_factory)
        await runtime.services['research'].close()
        ctx.services['research']=Reader()
        first=await search(SearchInput(query='example'),ctx)
        assert first.coverage['returned']==2 and first.coverage['complete'] is False
        assert first.next_cursor=='snapshot|2'
        last=await search(SearchInput(query='example',cursor='2'),ctx)
        assert last.coverage['complete'] and not last.next_cursor
        assert not last.coverage['site_search_complete'] and not last.coverage['report_contents_read']
    asyncio.run(scenario())
