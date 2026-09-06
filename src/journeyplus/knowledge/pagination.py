"""Workspace-local, signed continuation over an immutable search result."""
import base64
from copy import deepcopy
import hashlib
import hmac
import json
import secrets
import time


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _decode(value):
    return base64.urlsafe_b64decode(value+'='*((-len(value))%4))


def _cursor(state, search_ref, offset):
    record=state['route_searches'][search_ref]
    payload=json.dumps({'search_ref':search_ref,'offset':offset,'snapshot_ref':record['snapshot_ref'],
                        'query_hash':record['query_hash'],'order':'route-v1','expires_at':record['expires_at']},
                       sort_keys=True,separators=(',',':')).encode()
    key=bytes.fromhex(state.setdefault('route_cursor_key',secrets.token_hex(32)))
    return _encode(payload)+'.'+_encode(hmac.digest(key,payload,'sha256'))


def store_search(state,result,query_hash,*,now=None,evaluation_context=None):
    now=time.time() if now is None else now
    records=state.setdefault('route_searches',{})
    for ref in list(records):
        if records[ref]['expires_at']<=now:del records[ref]
    ref=secrets.token_hex(16)
    records[ref]={'snapshot_ref':result['snapshot_ref'],'snapshot':deepcopy(result['snapshot']),
                  'query_hash':query_hash,'expires_at':now+3600,'evaluation_context':evaluation_context,
                  'route_refs':list(result['server_routes']),
                  'envelope':{k:deepcopy(v) for k,v in result.items() if k not in {'server_routes','server_steps','snapshot'}}}
    state['routes'].update(result['server_routes'])
    state['steps'].update(result['server_steps'])
    state.setdefault('route_search_refs',{}).update({route_ref:ref for route_ref in result['server_routes']})
    return search_page(state,ref,0)


def search_page(state,search_ref,offset,*,page_size=8):
    record=state['route_searches'][search_ref]
    result=deepcopy(record['envelope']);refs=record['route_refs'][offset:offset+page_size]
    cards=[state['routes'][ref] for ref in refs]
    result['data']['cards']=cards
    result['data']['steps']={sid:state['steps'][sid] for card in cards for sid in card['step_refs']}
    result['coverage'].update(returned_count=len(cards),presentation_has_more=offset+len(cards)<len(record['route_refs']))
    result['expansions']=[{'ref':ref,'kind':'ROUTE','aspects':['ELIGIBILITY','PRICE'],'reason':'展开完整方案'} for ref in refs]
    result['next_cursor']=_cursor(state,search_ref,offset+len(cards)) if result['coverage']['presentation_has_more'] else None
    return result


def continue_search(state,cursor,*,current_snapshot,query_hash=None,now=None,evaluation_context=None):
    now=time.time() if now is None else now
    try:
        body,mac=cursor.split('.')
        payload=_decode(body)
        if not hmac.compare_digest(_decode(mac),hmac.digest(bytes.fromhex(state['route_cursor_key']),payload,'sha256')):
            raise ValueError('signature')
        value=json.loads(payload);record=state['route_searches'][value['search_ref']]
        if set(value)!={'search_ref','offset','snapshot_ref','query_hash','order','expires_at'}:raise ValueError('shape')
        if value['order']!='route-v1' or type(value['offset']) is not int or not 0<=value['offset']<=len(record['route_refs']):raise ValueError('position')
        if value['expires_at']!=record['expires_at'] or value['expires_at']<=now:raise ValueError('expired')
        if value['snapshot_ref']!=record['snapshot_ref'] or current_snapshot!=record['snapshot']:raise ValueError('snapshot')
        if record.get('evaluation_context')!=evaluation_context:raise ValueError('evaluation context')
        if value['query_hash']!=record['query_hash'] or (query_hash is not None and query_hash!=record['query_hash']):raise ValueError('query')
        return search_page(state,value['search_ref'],value['offset'])
    except (KeyError,ValueError,TypeError):
        return {'schema_version':1,'status':'EXPIRED','data':{},'coverage':{'search_complete':False},
                'caveats':['路线续页已失效或查询条件改变，请重新查询；旧卡片仍保留原快照。'],
                'expansions':[],'provenance':[]}
