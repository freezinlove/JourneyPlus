"""Optional HTTP JSON search adapter; unconfigured scope is explicitly unavailable."""
import os
import json
from urllib.parse import urlsplit
import httpx


def pointer(document,path):
    if path is None:return None
    if path=='':return document
    if not path.startswith('/'):raise ValueError('Expected JSON Pointer')
    value=document
    for part in path[1:].split('/'):
        key=part.replace('~1','/').replace('~0','~')
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


class HttpJsonSearch:
    def __init__(self,config=None,client=None):
        self.config=config
        self.client=client or httpx.AsyncClient(timeout=20,follow_redirects=False)
        self.enabled=False
        self.failure='SEARCH_PROVIDER_NOT_CONFIGURED'

    async def initialize(self):
        if not self.config:return
        try:
            if urlsplit(self.config['endpoint']).scheme!='https':raise ValueError('HTTPS required')
            for field in ('title','url','snippet','observed_at'):
                if field not in self.config['fields']:raise ValueError('Field mapping required, use explicit null for absent fields')
            await self._request({'query':'travel','limit':1,'cursor':None,'domains':[]})
            self.enabled=True;self.failure=None
        except Exception:self.failure='INVALID_SEARCH_CONFIGURATION'

    async def _request(self,payload):
        config=self.config
        headers={}
        if config.get('header_name'):
            secret=os.environ.get(config['header_secret_env'])
            if not secret:raise ValueError('Missing configured authentication environment variable')
            headers[config['header_name']]=secret
        async with self.client.stream('POST',config['endpoint'],json=payload,headers=headers,timeout=20) as response:
            response.raise_for_status()
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>1_000_000:raise ValueError('Search response exceeds one megabyte')
        data=json.loads(body)
        rows=pointer(data,config['results_pointer'])
        if not isinstance(rows,list):raise ValueError('Search results must be an array')
        results=[]
        for item in rows[:min(10,payload['limit'])]:
            row={key:pointer(item,path) for key,path in config['fields'].items()}
            if not isinstance(row['title'],str) or not isinstance(row['url'],str) or urlsplit(row['url']).scheme!='https':raise ValueError('Invalid search result')
            results.append(row)
        return {'results':results,'next_cursor':pointer(data,config.get('next_cursor_pointer')),'scope_description':'Configured HTTP JSON search provider'}

    async def search(self,args):
        if not self.enabled:return {'unavailable':self.failure}
        try:return await self._request({'query':args.query,'limit':args.limit,'cursor':args.cursor,'domains':args.domains})
        except httpx.HTTPError:return {'unavailable':'SOURCE_UNAVAILABLE'}
        except (KeyError,ValueError,TypeError):return {'unavailable':'INVALID_SEARCH_RESPONSE'}

    async def close(self):await self.client.aclose()
