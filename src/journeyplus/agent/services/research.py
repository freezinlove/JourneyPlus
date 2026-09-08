"""Public HTTPS reads and discovery, independent of chat and published routes."""
import asyncio
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import socket
from time import monotonic
from urllib.parse import urlsplit,urljoin,urlunsplit
import httpx
from selectolax.parser import HTMLParser


class PublicResearch:
    def __init__(self, enabled=False, client=None, search_backend=None):
        self.enabled=enabled
        self.search_backend=search_backend
        self.client=client or httpx.AsyncClient(follow_redirects=False,timeout=20)
        self.cache={}
        self.index=[]
        self.index_at=0
        self.searches={}

    async def close(self):
        await self.client.aclose()
        if self.search_backend:await self.search_backend.close()

    async def validate_url(self,url):
        parts=urlsplit(url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.port not in {None,443}:
            raise ValueError('Only public HTTPS URLs without credentials are supported')
        records=await asyncio.get_running_loop().getaddrinfo(parts.hostname,443,type=socket.SOCK_STREAM)
        if not records or any(not ipaddress.ip_address(record[4][0]).is_global for record in records):
            raise ValueError('Private, local or non-global addresses are not permitted')
        return records[0][4][0]

    async def page(self,url,refresh=False,max_chars=12000):
        if not self.enabled:raise PermissionError('Agent public research is disabled')
        cached=self.cache.get(url)
        if cached and not refresh and monotonic()-cached[0]<900:
            return {**cached[1],'cache_hit':True,'text':cached[1]['text'][:max_chars],
                    'truncated':cached[1].get('raw_truncated',False) or cached[1]['content_length']>min(max_chars,len(cached[1]['text']))}
        current=url
        total=0
        async with asyncio.timeout(20):
            for redirect in range(4):
                address=await self.validate_url(current)
                parts=urlsplit(current)
                authority='['+address+']' if ':' in address else address
                pinned=urlunsplit((parts.scheme,authority,parts.path,parts.query,''))
                async with self.client.stream('GET',pinned,headers={'Host':parts.hostname,'User-Agent':'JourneyPlus/1.0 public research'},extensions={'sni_hostname':parts.hostname}) as response:
                    if response.is_redirect:
                        if redirect==3:raise ValueError('Redirect limit exceeded')
                        current=urljoin(current,response.headers.get('location',''))
                        continue
                    response.raise_for_status()
                    body=bytearray()
                    raw_truncated=False
                    async for chunk in response.aiter_bytes():
                        remaining=1_000_000-len(body)
                        body.extend(chunk[:remaining]);total+=len(chunk)
                        if len(chunk)>remaining:
                            raw_truncated=True
                            break
                    html=body.decode('utf-8',errors='replace')
                    break
            else:raise ValueError('Page unavailable')
        from journeyplus.agent.harness.execution import blocking_call
        result,content=await blocking_call(parse_page,url,current,body,html,max_chars,raw_truncated)
        self.cache[url]=(monotonic(),result)
        while len(self.cache)>128:self.cache.pop(next(iter(self.cache)))
        return {**result,'text':content[:max_chars]}

    async def search(self,args):
        if not self.enabled:raise PermissionError('Agent public research is disabled')
        if args.scope=='web':
            return await self.search_backend.search(args) if self.search_backend else {'unavailable':'SEARCH_PROVIDER_NOT_CONFIGURED'}
        query_hash=hashlib.sha256(json.dumps([args.query,args.scope,args.domains],ensure_ascii=False).encode()).hexdigest()
        if args.cursor:
            identity,_,offset=args.cursor.rpartition('|')
            saved=self.searches.get(identity)
            if not saved or saved[0]!=query_hash or monotonic()-saved[1]>900 or not offset.isdigit():
                raise ValueError('STALE_REFERENCE: cursor does not identify this search snapshot')
            return self._search_page(saved[2],identity,int(offset),args.limit)
        if not self.index or monotonic()-self.index_at>86400:
            page=await self.page('https://statusmatcher.com/',max_chars=30000)
            observed=list(page['links'])
            directories=[link for link in observed if urlsplit(link['url']).hostname in {'statusmatcher.com','www.statusmatcher.com'} and urlsplit(link['url']).path in {'/airlines','/hotels','/auto'}]
            for directory in directories[:3]:
                listing=await self.page(directory['url'],max_chars=30000)
                observed.extend(listing['links'])
            self.index=list({link['url']:link for link in observed if urlsplit(link['url']).hostname in {'statusmatcher.com','www.statusmatcher.com'} and '/company/' in link['url']}.values())
            self.index_at=monotonic()
            if not self.index:return {'unavailable':'DISCOVERY_UNAVAILABLE'}
        tokens=args.query.casefold().split()
        scored=[]
        for link in self.index:
            haystack=(link['title']+' '+urlsplit(link['url']).path.replace('-',' ')).casefold()
            score=sum(token in haystack for token in tokens)
            if score:scored.append((score,link))
        scored.sort(key=lambda x:-x[0])
        results=[{**item,'snippet':'Public company page observed on StatusMatcher','source':'statusmatcher_builtin'} for _,item in scored]
        if results:
            page=await self.page(results[0]['url'])
            from journeyplus.agent.report_pages import list_report_candidates
            reports=[{'url':item['url'],'title':item.get('direction') or 'Application report','snippet':'Report link observed in company report list','source':'statusmatcher_builtin'} for item in list_report_candidates(page['raw_html'],page['final_url'])]
            results=results[:1]+reports+results[1:]
        results=list({result['url']:result for result in results}.values())
        if args.domains:
            results=[result for result in results if urlsplit(result['url']).hostname in args.domains]
        from uuid import uuid4
        identity=str(uuid4());self.searches[identity]=(query_hash,monotonic(),results)
        while len(self.searches)>128:self.searches.pop(next(iter(self.searches)))
        return self._search_page(results,identity,0,args.limit)

    @staticmethod
    def _search_page(results,identity,offset,limit):
        if offset>len(results):raise ValueError('Invalid search cursor offset')
        return {'results':results[offset:offset+limit],'scope_description':'Observed homepage-linked public directories and first matched company report links; not a complete site search',
                'coverage':{'scope':'discovered_link_snapshot','total':len(results),'offset':offset,
                            'returned':len(results[offset:offset+limit]),'complete':offset+limit>=len(results),
                            'site_search_complete':False,'report_contents_read':False},
                'next_cursor':identity+'|'+str(offset+limit) if len(results)>offset+limit else None}


def parse_page(url,current,body,html,max_chars,raw_truncated):
    tree=HTMLParser(html)
    title=tree.css_first('title')
    links=[]
    for node in tree.css('a[href]'):
        link=urljoin(current,node.attributes['href'])
        if link.startswith('https://') and link not in {x['url'] for x in links}:
            links.append({'url':link,'title':node.text(separator=' ',strip=True)[:300]})
    for node in tree.css('script,style,noscript,nav,footer'):node.decompose()
    content=(tree.body or tree.root).text(separator=' ',strip=True)
    result={'url':url,'final_url':current,'title':title.text(strip=True)[:500] if title else '',
            'text':content[:30000],'links':links,'observed_at':datetime.now(timezone.utc).isoformat(),
            'content_hash':hashlib.sha256(body).hexdigest(),'content_length':len(content),'truncated':len(content)>max_chars,'raw_html':html,
            'cache_hit':False,'raw_truncated':raw_truncated,'retained_raw_bytes':len(body)}
    # The artifact limit includes JSON escaping and extracted metadata, not
    # just downloaded bytes. Preserve an explicit retained prefix and URL.
    while len(json.dumps(result,ensure_ascii=False).encode())>950_000:
        result['raw_truncated']=True
        if result['links'] and len(json.dumps(result['links'],ensure_ascii=False).encode())>100_000:
            result['links']=result['links'][:len(result['links'])//2]
            result['links_truncated']=True
        else:
            result['raw_html']=result['raw_html'][:int(len(result['raw_html'])*.8)]
        result['retained_raw_bytes']=len(result['raw_html'].encode())
    result['truncated']=result['raw_truncated'] or len(content)>max_chars
    result['content_hash_scope']='retained_download_prefix' if raw_truncated else 'complete_response'
    return result,content
