"""Explicit route inputs; immutable query artifacts replace implicit last-query state."""
from journeyplus.agent.harness.execution import blocking_tool
from journeyplus.agent.services.route_metrics import metrics
from journeyplus.agent.services.route_objects import RouteObject
from copy import deepcopy
from uuid import UUID
from journeyplus.agent.harness.contracts import ToolResult
from .contracts import RouteRequest
import json


def merge_query(base, patch):
    if hasattr(patch,'model_dump'):
        patch=patch.model_dump(mode='json',exclude_unset=True)
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
            elif not detail:
                # Search returns the cost assessment, not repeated full fee
                # conditions for every path sharing the same step. The immutable
                # route and inspect retain every fee, condition and association.
                value['cost'][key+'_count']=len(value['cost'].pop(key))
                value['cost']['details_omitted']=True
                value['needs_inspection']=True
    caveats=value.get('material_caveats',[])
    value['material_caveats']=caveats if detail else []
    value['material_caveat_count']=len(caveats)
    value['caveats_truncated']=not detail and bool(caveats)
    if value['caveats_truncated']:
        value['needs_inspection']=True
    classification=value.pop('classification',None)
    value.pop('classification_scope',None)
    value['constraint_match']={'NEARBY':'CONFLICT','EXCLUDED':'CONFLICT','MATCH':'SATISFIES','CONFLICT':'CONFLICT','UNKNOWN':'UNKNOWN'}.get(classification,classification)
    value['assessment_scope']='constraint_match only evaluates query filters. eligibility is personal eligibility; challenge describes challenge requirements independently.'
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
    searched=bool(raw.get('searched_published_graph_complete',raw.get('search_complete')))
    return {**raw,'search_complete':searched,'complete':searched and offset+returned>=total,
            **({'stopped_reason':None,'knowledge_gap_reason':'KNOWLEDGE_GAPS'}
               if searched and raw.get('stopped_reason')=='KNOWLEDGE_GAPS' else {}),
            **({'knowledge_gap_scope':'catalog_wide; not evidence of missing routes for this query'}
               if raw.get('pending_activity_count') or raw.get('incomplete_published_activity_count') else {}),
            'returned':returned,'returned_count':returned,'total':total,'offset':offset,
            'presentation_has_more':offset+returned<total,
            'unread_candidate_count':max(0,total-offset-returned),
            'retrieval_complete':offset+returned>=total,
            'omissions':['additional_candidates'] if offset+returned<total else []}


def scope_coverage(payload,total,returned,offset=0):
    value=coverage(payload['coverage'],total,returned,offset)
    if payload.get('resolution',{}).get('unresolved_sources'):
        value['complete']=False
        value['omissions']=[*value['omissions'],'unresolved_query_sources']
    return value


@blocking_tool
def evaluate(args, ctx):
    from journeyplus.agent.services.query_lineage import build,read_context
    if args.operation!='search':
        routes=[];steps={};origin_queries={};origin_scopes={}
        for ref in args.route_refs:
            obj=RouteObject.read(ctx.artifact_port,ctx.workspace_id,ref)
            root_ref,route=obj.root_ref,obj.route
            origin_scopes[root_ref]={'result_ref':root_ref,'resolution':obj.resolution,'coverage':obj.coverage}
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
                                 'origin_scopes':list(origin_scopes.values()),
                                 'meaning':'Selected result objects only; their endpoints are not new user query constraints.'}}
        if args.operation=='inspect':data['steps']=list(steps.values())
        else:data['metrics']={key:value for key,value in metrics(routes).items() if key!='items'}
        incomplete=any(scope['resolution'].get('unresolved_sources') for scope in origin_scopes.values())
        return ToolResult(status='PARTIAL' if incomplete else 'OK',data=data,
            coverage={'complete':not incomplete,'retrieval_complete':True,'scope':'selected_objects',
                      'returned':len(routes),'total':len(routes),
                      'omissions':['unresolved_query_sources'] if incomplete else []})
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
            return ToolResult(status='PARTIAL' if any(c.get('constraint_match')=='UNKNOWN' for c in selected) or result.get('resolution',{}).get('unresolved_sources') or not result['coverage'].get('searched_published_graph_complete',result['coverage'].get('search_complete')) else 'OK',
                data={'query_ref':args.query_ref,'search_metrics':result.get('search_metrics'),
                'route_refs':[r['ref'] for r in selected], 'candidates':selected,**result.get('resolution',{})},
                coverage=scope_coverage(result,len(refs),len(selected),int(offset)),
                artifact_refs=[args.query_ref,result_ref],effective_input=result.get('effective_input',{}),
                next_cursor=next_cursor)
        query=merge_query(previous['payload'],args.patch or {})
    lineage=build(ctx,args,query.model_dump(mode='json'),previous if not args.query else None)
    from journeyplus.agent.services.query_lineage import validate_changes
    conflict=validate_changes(ctx,args,lineage)
    if conflict:
        return conflict
    context_ref=ctx.artifact_port.put(ctx.workspace_id,'QUERY_CONTEXT',lineage,call_id=ctx.call_id,turn_id=ctx.turn_id)
    query_ref=ctx.artifact_port.put(ctx.workspace_id,'QUERY',query.model_dump(mode='json'),call_id=ctx.call_id,turn_id=ctx.turn_id,source_refs=[context_ref])
    evaluation=ctx.services['route_queries'].evaluate(query,context=ctx,limit=args.limit)
    if evaluation.get('error'):
        error=evaluation['error']
        error.data.update(query_ref=query_ref,query_context=lineage,effective_query=query.model_dump(mode='json'))
        error.artifact_refs.append(query_ref)
        return error
    result,actual=evaluation['result'],evaluation['actual']
    sources,target,unresolved=evaluation['sources'],evaluation['target'],evaluation['unresolved']
    # Preserve the reader's disclosure policy. Workflow UNKNOWN candidates
    # remain visible and explicitly uncertain; proven conflicts are not paged.
    from collections import Counter
    classifications=Counter(r['classification'] for r in result['server_routes'].values())
    presentation_classes=result.get('presentation_classes',['MATCH'])
    matching=[key for key,r in result['server_routes'].items() if r['classification'] in presentation_classes]
    payload={'query_ref':query_ref,'routes':result['server_routes'],'steps':result['server_steps'],'snapshot':result['snapshot'],
             'route_order':matching,'coverage':result['coverage'],
             'search_metrics':{'matching_count':classifications.get('MATCH',0),'presented_count':len(matching),'candidate_counts':dict(classifications),
                               'scope':('MATCH and UNKNOWN candidates are paged separately by their constraint_match label; UNKNOWN requires inspection and is not a proven match.' if 'UNKNOWN' in presentation_classes else
                                        'Only candidates satisfying explicit query filters are paged. All assessed alternatives remain in this result artifact; UNKNOWN is not a proven match.')},
             'resolution':{'resolved_sources':sources,'resolved_target':target,'unresolved_sources':unresolved},
             'effective_input':actual.model_dump(mode='json')}
    # The fields exposed by search must exist at the returned immutable member
    # reference too. Keep legacy calculation fields for renderers, and persist
    # the explicit subtotal/path view instead of returning uncitable aliases.
    for route in payload['routes'].values():
        view=route_summary(route,'',payload['steps'],detail=True)
        for key in ('path','source_versions','constraint_match','assessment_scope'):
            route[key]=deepcopy(view[key])
        if route.get('cost',{}).get('state')!='KNOWN':
            route['cost']['known_subtotal']=deepcopy(view['cost'].get('known_subtotal',[]))
            route['cost']['total']='UNKNOWN'
    ref=ctx.artifact_port.put(ctx.workspace_id,'ROUTES',payload,call_id=ctx.call_id,turn_id=ctx.turn_id)
    ids=payload['route_order']
    candidates,next_cursor=result_page(payload,ref,0,args.limit)
    return ToolResult(status='PARTIAL' if any(c.get('constraint_match')=='UNKNOWN' for c in candidates) or unresolved or not result['coverage'].get('searched_published_graph_complete',result['coverage']['search_complete']) else 'OK' if candidates else 'EMPTY',
        data={'query_ref':query_ref,'query_context':lineage,'effective_query':query.model_dump(mode='json'),'resolved_sources':sources,'resolved_target':target,
              'search_metrics':payload['search_metrics'],
              'unresolved_sources':unresolved,'route_refs':[r['ref'] for r in candidates],'candidates':candidates,
              },
        artifact_refs=[query_ref,ref],coverage=scope_coverage(payload,len(ids),len(candidates)),effective_input=actual.model_dump(mode='json'),
        next_cursor=next_cursor)
