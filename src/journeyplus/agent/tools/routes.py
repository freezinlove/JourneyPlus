"""Explicit route inputs; immutable query artifacts replace implicit last-query state."""
from journeyplus.agent.services.route_metrics import metrics
from journeyplus.agent.services.route_objects import RouteObject
from copy import deepcopy
from uuid import UUID
from journeyplus.models import StatusHolding, now_utc
from journeyplus.knowledge.routes import RouteService, RouteQuery
from journeyplus.agent.harness.contracts import ToolResult
from .contracts import RouteRequest
from sqlalchemy import select
import json


def merge_query(base, patch):
    allowed=set(RouteRequest.model_fields)
    if set(patch)-allowed:
        raise ValueError('Unknown RouteRequest patch fields')
    result=deepcopy(base)
    for key,value in patch.items():
        if key in {'sources','target'} or not isinstance(value,dict):
            if value is None:
                result.pop(key,None)
            else:
                result[key]=value
        else:
            current=result.get(key,{})
            for sub,item in value.items():
                if item is None:current.pop(sub,None)
                else:current[sub]=item
            result[key]=current
    return RouteRequest.model_validate(result)


def route_summary(route,root_ref,steps=None,*,detail=False):
    value={k:deepcopy(v) for k,v in route.items() if k not in {'fact_refs','selection_reasons'}}
    value['ref']=root_ref+'#route:'+route['ref']
    value['step_refs']=[root_ref+'#step:'+sid for sid in route['step_refs']]
    if steps is not None:
        ordered=[steps[sid] for sid in route['step_refs']]
        value['path']=[ordered[0]['from'],*[step['to'] for step in ordered]] if ordered else []
        versions=list(dict.fromkeys((step['activity_ref'],step['version_ref']) for step in ordered
                                    if 'activity_ref' in step and 'version_ref' in step))
        value['source_versions']=[{'activity_ref':activity,'version_ref':version} for activity,version in versions]
    if not detail and steps is not None:
        # Keep explicit endpoints: a route passing through a program is not a
        # route ending at that program. Full steps remain addressable by ref.
        value.pop('step_refs',None)
    if 'cost' in value:
        if value['cost'].get('state')!='KNOWN':
            # A partial sum is not a total, especially when the only known
            # component is zero. Make that distinction explicit in the data.
            value['cost']['known_subtotal']=value['cost'].pop('totals',[])
            value['cost']['total']='UNKNOWN'
        for key in ('alternative_items','conditional_items'):
            if not value['cost'].get(key):value['cost'].pop(key,None)
    caveats=value.get('material_caveats',[])
    value['material_caveats']=caveats if detail else caveats[:1]
    value['material_caveat_count']=len(caveats)
    value['caveats_truncated']=not detail and len(caveats)>1
    value['classification_scope']='query_constraint_evaluation; not personal eligibility or application approval'
    return value


def result_page(payload,root_ref,offset,limit):
    # PostgreSQL JSONB reorders object keys. A cursor must index an explicit
    # immutable list, never Python dict insertion order before/after storage.
    refs=payload.get('route_order',sorted(payload['routes']));selected=[]
    paths={}
    if payload.get('steps') is not None:
        for key in refs:
            route=payload['routes'][key]
            ordered=[payload['steps'][sid] for sid in route['step_refs']]
            path=tuple([ordered[0]['from'],*[step['to'] for step in ordered]]) if ordered else ()
            paths.setdefault(path,[]).append(key)
    for key in refs[offset:offset+limit]:
        candidate=route_summary(payload['routes'][key],root_ref,payload.get('steps'))
        if 'path' in candidate:
            variants=paths[tuple(candidate['path'])]
            if len(variants)>1:
                candidate['same_path_variants']={'index':variants.index(key)+1,'total':len(variants)}
        # Leave room for the query/coverage envelope within the 12 KB result
        # budget; small pages repeatedly resend the same evidence and schemas.
        if selected and len(json.dumps([*selected,candidate],ensure_ascii=False).encode())>9000:break
        selected.append(candidate)
    end=offset+len(selected)
    return selected, root_ref+'|'+str(end) if end<len(refs) else None


def coverage(raw,total,returned,offset=0):
    return {**raw,'complete':bool(raw.get('search_complete')) and offset+returned>=total,
            **({'knowledge_gap_scope':'catalog_wide; not evidence of missing routes for this query'}
               if raw.get('pending_activity_count') or raw.get('incomplete_published_activity_count') else {}),
            'returned':returned,'returned_count':returned,'total':total,'offset':offset,
            'presentation_has_more':offset+returned<total,
            'unread_candidate_count':max(0,total-offset-returned),
            'retrieval_complete':offset+returned>=total,
            'omissions':['additional_candidates'] if offset+returned<total else []}


async def evaluate(args, ctx):
    if args.operation!='search':
        routes=[];steps={};origin_queries={}
        for ref in args.route_refs:
            obj=RouteObject.read(ctx.artifact_port,ctx.workspace_id,ref)
            root_ref,route=obj.root_ref,obj.route
            if obj.query_ref and obj.query_ref not in origin_queries:
                original=ctx.artifact_port.read(ctx.workspace_id,obj.query_ref)
                if original['kind']!='QUERY':raise ValueError('Route origin must identify a QUERY snapshot')
                origin_queries[obj.query_ref]=original['payload']
            candidate=route_summary(route,root_ref,obj.steps,detail=True)
            if args.operation == 'inspect':
                from journeyplus.agent.services.materials import compact
                for sid in route['step_refs']:
                    step_ref=root_ref+'#step:'+sid
                    step=compact({k:v for k,v in obj.steps[sid].items()
                                  if k not in {'fact_refs','evidence_ids','from_tier_id','to_tier_id'}})
                    step['ref']=step_ref
                    # Preserve original condition text once, together with its
                    # evaluation. Shared steps are returned once across routes.
                    reasons={check.get('reason') for check in step.get('constraint_checks',[])}
                    step['material_caveats']=[v for v in step.get('material_caveats',[]) if v not in reasons]
                    for check in step.get('constraint_checks',[]):
                        if check.get('expected')==check.get('reason'):check.pop('expected',None)
                    steps[step_ref]=step
            routes.append(candidate)
        data={'route_refs':args.route_refs,'candidates':routes,
              'retrieval_scope':{'operation':args.operation,'new_search_performed':False,
                                 'origin_queries':[{'query_ref':ref,'effective_query':query}
                                                   for ref,query in origin_queries.items()],
                                 'meaning':'Selected result objects only; their endpoints are not new user query constraints.'}}
        if args.operation=='inspect':data['steps']=list(steps.values())
        else:data['metrics']={key:value for key,value in metrics(routes).items() if key!='items'}
        return ToolResult(data=data,coverage={"complete":True,"returned":len(routes),"total":len(routes),"omissions":[]})
    if args.query:
        query=args.query
    else:
        previous=ctx.artifact_port.read(ctx.workspace_id,args.query_ref)
        if previous['kind']!='QUERY':raise ValueError('query_ref must identify QUERY artifact')
        if args.cursor:
            # Cursor belongs to the original immutable result, never a fresh search.
            result_ref, _, offset=args.cursor.rpartition('|')
            result=ctx.artifact_port.read(ctx.workspace_id,result_ref)['payload']
            if result.get('query_ref')!=args.query_ref:raise ValueError('Cursor does not belong to query snapshot')
            if not offset.isdigit() or int(offset)<0:raise ValueError('Invalid route cursor offset')
            refs=result.get('route_order',sorted(result['routes']))
            if int(offset)>len(refs):raise ValueError('Invalid route cursor offset')
            selected,next_cursor=result_page(result,result_ref,int(offset),args.limit)
            return ToolResult(status='PARTIAL' if not result['coverage'].get('search_complete') else 'OK',
                data={'query_ref':args.query_ref,'effective_query':previous['payload'],
                'route_refs':[r['ref'] for r in selected], 'candidates':selected},coverage=coverage(result['coverage'],len(refs),len(selected),int(offset)),
                next_cursor=next_cursor)
        query=merge_query(previous['payload'],args.patch)
    unresolved=[];sources=[]
    with ctx.services['knowledge'].read() as s:
        identities=list(query.sources.identities)
        if query.sources.mode=='saved':
            holdings=list(s.scalars(select(StatusHolding).where((StatusHolding.valid_until.is_(None)) | (StatusHolding.valid_until>=now_utc().date()))))
        elif query.sources.holding_refs:
            holdings=[]
            for ref in query.sources.holding_refs:
                holding=s.get(StatusHolding,UUID(ref.removeprefix('holding:')))
                if holding is None:raise LookupError('Holding does not exist')
                holdings.append(holding)
        else:
            holdings=[]
        for h in holdings:
            if h.tier_id:
                identities.append({'ref':'tier:'+str(h.tier_id)})
            else:
                unresolved.append({'holding_ref':'holding:'+str(h.id),'program_name':h.program_display_name,'tier_name':h.tier_display_name,'code':'CATALOG_GAP'})
        for identity in identities:
            resolved=ctx.services['identities'].resolve(s,identity,require_tier=True,context=ctx)
            if resolved['status']!='OK':unresolved.append(resolved)
            else:sources.append(resolved)
        target=ctx.services['identities'].resolve(s,query.target,context=ctx) if query.target else None
        if target and target['status']!='OK':
            return ToolResult.failure(target['code'],'Target identity could not be bound',status=target['status'],candidates=target['candidates'])
        if unresolved and (query.sources.mode=='explicit' or not sources):
            ambiguous=any(item.get('status')=='AMBIGUOUS' for item in unresolved)
            return ToolResult(status='AMBIGUOUS' if ambiguous else 'NOT_FOUND',
                data={'resolved_sources':sources,'unresolved_sources':unresolved},
                error={'code':'IDENTITY_AMBIGUOUS' if ambiguous else 'CATALOG_GAP',
                       'message':'Requested sources could not all be resolved',
                       'candidates':[candidate for item in unresolved for candidate in item.get('candidates',[])][:10]})
        actual=RouteQuery(starting_tier_ids=list({UUID(r['tier_ref'][5:]) for r in sources}), use_saved_holdings=False,
            target_program_id=UUID(target['program_ref'][8:]) if target else None,
            target_tier_id=UUID(target['tier_ref'][5:]) if target and target['tier_ref'] else None,
            alliance=query.alliance,category=query.category,preferences=query.preferences,**query.constraints.model_dump())
        result=RouteService(s).query(actual,shortlist=args.limit)
    query_ref=ctx.artifact_port.put(ctx.workspace_id,'QUERY',query.model_dump(mode='json'),call_id=ctx.call_id)
    payload={'query_ref':query_ref,'routes':result['server_routes'],'steps':result['server_steps'],'snapshot':result['snapshot'],
             'route_order':list(result['server_routes']),'coverage':result['coverage']}
    ref=ctx.artifact_port.put(ctx.workspace_id,'ROUTES',payload,call_id=ctx.call_id)
    ids=list(payload['routes'])
    candidates,next_cursor=result_page(payload,ref,0,args.limit)
    return ToolResult(status='PARTIAL' if unresolved or not result['coverage']['search_complete'] else 'OK' if candidates else 'EMPTY',
        data={'query_ref':query_ref,'effective_query':query.model_dump(mode='json'),'resolved_sources':sources,'resolved_target':target,
              'unresolved_sources':unresolved,'route_refs':[r['ref'] for r in candidates],'candidates':candidates,
              },
        artifact_refs=[query_ref,ref],coverage={**coverage(result['coverage'],len(ids),len(candidates)),**({'complete':False} if unresolved else {})},effective_input=actual.model_dump(mode='json'),
        next_cursor=next_cursor)
