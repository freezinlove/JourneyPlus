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
    value['object_type']='route'
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
    if not detail and route.get('source_group'):
        # A union query is presented as a union, not as a per-membership
        # eligibility verdict. The exact supporting origin remains in inspect.
        value['from'] = route['source_group']['label']
        if value.get('path'):
            value['path'][0] = value['from']
    # Older snapshots may carry duplicate fee/placeholder fields.
    if isinstance(value.get('paid'),bool):
        value.pop('cost',None)
        for key in ('eligibility','challenge'):
            if value.get(key)=='UNKNOWN':value.pop(key,None)
    caveats=value.get('material_caveats',[])
    for key in ('material_caveats','material_caveat_count','caveats_truncated','assessment_scope'):
        value.pop(key,None)
    if caveats:
        if detail:value['material_caveats']=caveats
        else:
            value.update(material_caveat_count=len(caveats),caveats_truncated=True,needs_inspection=True)
    classification=value.pop('classification',None)
    value.pop('classification_scope',None)
    value['constraint_match']={'NEARBY':'CONFLICT','EXCLUDED':'CONFLICT','MATCH':'SATISFIES','CONFLICT':'CONFLICT','UNKNOWN':'UNKNOWN'}.get(classification,classification)
    return value


def result_page(payload,root_ref,offset,limit,read_payload=None):
    # PostgreSQL JSONB reorders object keys. A cursor must index an explicit
    # immutable list, never Python dict insertion order before/after storage.
    refs=payload.get('route_order',sorted(payload['routes']));selected=[]
    paths={}; route_paths={}
    if payload.get('steps') is not None:
        for key in refs:
            route=payload['routes'][key]
            ordered=[payload['steps'][sid] for sid in route['step_refs']]
            path=tuple([ordered[0]['from'],*[step['to'] for step in ordered]]) if ordered else ()
            paths.setdefault(path,[]).append(key)
            route_paths[key]=path
    for key in refs[offset:offset+limit if limit is not None else None]:
        candidate=route_summary(payload['routes'][key],root_ref,payload.get('steps'))
        if 'path' in candidate:
            variants=paths[route_paths[key]]
            if len(variants)>1:
                candidate['same_path_variants']={'index':variants.index(key)+1,'total':len(variants)}
        selected.append(candidate)
    end=offset+len(selected)
    cursor=root_ref+'|'+str(end) if end<len(refs) else payload.get('next_result_ref')+'|0' if payload.get('next_result_ref') else None
    if end==len(refs) and payload.get('next_result_ref') and read_payload and (limit is None or len(selected)<limit):
        following=payload['next_result_ref']
        extra,cursor=result_page(read_payload(following),following,0,
            None if limit is None else limit-len(selected),read_payload)
        selected.extend(extra)
    return selected,cursor


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
    value=coverage(payload['coverage'],payload.get('result_total',total),returned,payload.get('result_offset',0)+offset)
    value['page_offset']=offset
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
                    step['object_type']='step'
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
        try: RouteRequest.model_validate(previous['payload'])
        except ValueError: return ToolResult.failure('QUERY_EXPIRED','Matching rules changed; start a new query with identities and free_only.')
        if args.cursor:
            # Cursor belongs to the original immutable result, never a fresh search.
            result_ref, _, offset=args.cursor.rpartition('|')
            result=ctx.artifact_port.read(ctx.workspace_id,result_ref)['payload']
            from journeyplus.knowledge.simple_matching import POLICY
            if result.get('matching_policy') != POLICY: return ToolResult.failure('QUERY_EXPIRED','Matching rules changed; start a new query.')
            if result.get('query_ref')!=args.query_ref:raise ValueError('Cursor does not belong to query snapshot')
            if not offset.isdigit() or int(offset)<0:raise ValueError('Invalid route cursor offset')
            refs=result.get('route_order',sorted(result['routes']))
            if int(offset)>len(refs):raise ValueError('Invalid route cursor offset')
            selected,next_cursor=result_page(result,result_ref,int(offset),args.limit,lambda ref:ctx.artifact_port.read(ctx.workspace_id,ref)['payload'])
            return ToolResult(status='PARTIAL' if any(c.get('constraint_match')=='UNKNOWN' for c in selected) or result.get('resolution',{}).get('unresolved_sources') or not result['coverage'].get('searched_published_graph_complete',result['coverage'].get('search_complete')) else 'OK',
                data={'query_ref':args.query_ref,'search_metrics':result.get('search_metrics'),
                'route_refs':[r['ref'] for r in selected], 'candidates':selected,**result.get('resolution',{})},
                coverage=scope_coverage(result,len(refs),len(selected),int(offset)),
                artifact_refs=[args.query_ref,result_ref],effective_input=result.get('effective_input',{}),
                next_cursor=next_cursor)
        query=merge_query(previous['payload'],args.patch or {})
    lineage=build(ctx,args,query.model_dump(mode='json'),previous if not args.query else None)
    context_ref=ctx.artifact_port.put(ctx.workspace_id,'QUERY_CONTEXT',lineage,call_id=ctx.call_id,turn_id=ctx.turn_id)
    query_ref=ctx.artifact_port.put(ctx.workspace_id,'QUERY',query.model_dump(mode='json'),call_id=ctx.call_id,turn_id=ctx.turn_id,source_refs=[context_ref])
    evaluation=ctx.services['route_queries'].evaluate(query,context=ctx,limit=args.limit)
    if evaluation.get('error'):
        error=evaluation['error']
        error.data.update(query_ref=query_ref,query_context=lineage,effective_query=query.model_dump(mode='json'))
        if evaluation.get('source_selection'):error.data['source_selection']=evaluation['source_selection']
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
    payload={'matching_policy':result.get('matching_policy'),'query_ref':query_ref,'routes':result['server_routes'],'steps':result['server_steps'],'snapshot':result['snapshot'],
             'route_order':matching,'coverage':result['coverage'],
             'search_metrics':{'matching_count':classifications.get('MATCH',0),'presented_count':len(matching),'candidate_counts':dict(classifications),
                               'scope':('MATCH and UNKNOWN candidates are paged separately by their constraint_match label; UNKNOWN requires inspection and is not a proven match.' if 'UNKNOWN' in presentation_classes else
                                        'Only selected shortest membership paths are retained. Free/paid is the only fee filter; region and exact prices are activity details. No exploration history is stored.')},
             'resolution':{'resolved_sources':sources,'resolved_target':target,'unresolved_sources':unresolved,
                           'source_selection':evaluation['source_selection']},
             'effective_input':actual.model_dump(mode='json')}
    # The fields exposed by search must exist at the returned immutable member
    # reference too. Keep actual paths and version bindings for inspection.
    for route in payload['routes'].values():
        route['source_mode']=query.sources.mode
        if len(sources) > 1:
            route['source_group']={'label':'所选会籍组合', 'count':len(sources)}
        view=route_summary(route,'',payload['steps'],detail=True)
        for key in ('path','source_versions','constraint_match'):
            route[key]=deepcopy(view[key])
    from journeyplus.agent.services.route_storage import save_routes
    ref,payload=save_routes(ctx,payload)
    ids=payload['route_order']
    candidates,next_cursor=result_page(payload,ref,0,args.limit,lambda ref:ctx.artifact_port.read(ctx.workspace_id,ref)['payload'])
    return ToolResult(status='PARTIAL' if any(c.get('constraint_match')=='UNKNOWN' for c in candidates) or unresolved or not result['coverage'].get('searched_published_graph_complete',result['coverage']['search_complete']) else 'OK' if candidates else 'EMPTY',
        data={'query_ref':query_ref,'query_context':lineage,'effective_query':query.model_dump(mode='json'),'resolved_sources':sources,'resolved_target':target,
              'source_selection':evaluation['source_selection'],
              'search_metrics':payload['search_metrics'],
              'unresolved_sources':unresolved,'route_refs':[r['ref'] for r in candidates],'candidates':candidates,
              },
        artifact_refs=[query_ref,ref],coverage=scope_coverage(payload,len(ids),len(candidates)),effective_input=actual.model_dump(mode='json'),
        next_cursor=next_cursor)


def capacity_page(result):
    """Shorten only whole candidates after actual context admission fails."""
    rows=result.data.get('candidates',[])
    if result.error or not result.data.get('query_ref') or len(rows)<=1:
        return None
    value=result.model_copy(deep=True)
    count=max(1,len(rows)//2)
    selected=rows[:count]
    value.data['candidates']=selected
    value.data['route_refs']=[row['ref'] for row in selected]
    total=value.coverage['total'];offset=value.coverage.get('offset',0)
    root=selected[-1]['ref'].split('#')[0]
    first_root=selected[0]['ref'].split('#')[0]
    local_count=sum(row['ref'].split('#')[0]==root for row in selected)
    local_offset=value.coverage.get('page_offset',0) if root==first_root else 0
    value.next_cursor=root+'|'+str(local_offset+local_count)
    value.coverage.update(complete=False,returned=count,returned_count=count,
        presentation_has_more=True,unread_candidate_count=max(0,total-offset-count),
        retrieval_complete=False,pagination_reason='context_capacity')
    value.coverage['omissions']=list(dict.fromkeys([*value.coverage.get('omissions',[]),'additional_candidates']))
    return value
