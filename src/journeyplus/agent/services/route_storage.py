"""Page only final routes into the existing immutable artifact store."""
import json
from copy import deepcopy


def save_routes(ctx, payload, *, once=False, max_bytes=700000):
    order=payload.get('route_order', list(payload['routes']))
    base={k:deepcopy(v) for k,v in payload.items() if k not in {'routes','steps','route_order','snapshot'}}
    def page(keys,offset):
        routes={k:payload['routes'][k] for k in keys}
        used={sid for r in routes.values() for sid in r['step_refs']}
        steps={sid:payload['steps'][sid] for sid in used}
        return {**base,'routes':routes,'steps':steps,'route_order':list(keys),
                'snapshot':{s['activity_ref']:s['version_ref'] for s in steps.values()},
                'result_total':len(order),'result_offset':offset}
    groups=[];keys=[];offset=0
    for key in order:
        candidate=page([*keys,key],offset)
        if keys and len(json.dumps(candidate,ensure_ascii=False,default=str).encode())>max_bytes:
            groups.append(page(keys,offset));offset+=len(keys);keys=[]
        keys.append(key)
    groups.append(page(keys,offset))
    put=ctx.artifact_port.put_once if once else ctx.artifact_port.put
    next_ref=None;first=None
    for value in reversed(groups):
        value['next_result_ref']=next_ref
        next_ref=put(ctx.workspace_id,'ROUTES',value,call_id=ctx.call_id,turn_id=ctx.turn_id)
        first=value
    return next_ref, first
