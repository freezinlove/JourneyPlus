"""Independent catalogue and version-bound activity reading."""
from journeyplus.agent.harness.execution import blocking_tool
from uuid import UUID
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.agent.services.identities import canonical
from journeyplus.agent.services.materials import sectioned, summary
import hashlib,json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


@blocking_tool
def catalog(args, ctx):
    request=args.model_dump(mode='json',exclude={'cursor','limit'})
    request['query']=canonical(args.query)
    query_hash=digest(request)
    if args.cursor:
        ref,_,offset=args.cursor.rpartition('|')
        data=ctx.artifact_port.read(ctx.workspace_id,ref)['payload']
        if data.get('catalog_query_hash')!=query_hash or not offset.isdigit():raise ValueError('STALE_REFERENCE: catalog cursor does not match the query')
        return catalog_page(data['candidates'],ref,int(offset),args.limit)
    with ctx.services['knowledge'].read() as s:
        programs, tiers, aliases = ctx.services['identities'].catalog(s)
        if not programs:
            return ToolResult.failure('KNOWLEDGE_NOT_READY',
                '当前没有可用的匹配目录：可能尚未生产资料，或相关活动已结束。此时无法通过当前目录解析会籍；可以稍后重新查询。',status='UNAVAILABLE')
        allowed = None
        if args.program:
            resolved=ctx.services['identities'].resolve(s,args.program,context=ctx)
            if resolved['status']!='OK':
                return ToolResult.failure(resolved['code'],'Program could not be uniquely resolved',status=resolved['status'],candidates=resolved['candidates'])
            allowed=resolved['program_ref']
        query=canonical(args.query)
        results=[]
        for program in programs:
            pref='program:'+str(program.id)
            if allowed and pref!=allowed:
                continue
            pa=[{'name':a.normalized_alias,'locale':a.locale,'origin':a.origin} for a in aliases if a.program_id==program.id and a.tier_id is None]
            match=any(query in canonical(n) or len(canonical(n))>=4 and canonical(n) in query
                      for n in [program.display_name,program.canonical_key,*[a['name'] for a in pa]])
            if args.kind!='tier' and match:
                results.append({'ref':pref,'name':program.display_name,'category':program.category,'aliases':pa,
                    'tiers_preview':[{'ref':'tier:'+str(t.id),'name':t.display_name} for t in tiers if t.program_id==program.id][:10],'match_basis':'name_or_alias'})
            if args.kind!='program':
                for tier in tiers:
                    if tier.program_id!=program.id:
                        continue
                    ta=[{'name':a.normalized_alias,'locale':a.locale,'origin':a.origin} for a in aliases if a.tier_id==tier.id]
                    combined=canonical(program.display_name+' '+tier.display_name+' '+' '.join(a['name'] for a in pa+ta))
                    if query in canonical(tier.display_name) or any(query in canonical(a['name']) for a in ta) or all(token in combined for token in query.split()):
                        results.append({'ref':'tier:'+str(tier.id),'program_ref':pref,'program_name':program.display_name,'name':tier.display_name,'aliases':ta,'match_basis':'tier_name_or_alias'})
    ref=ctx.artifact_port.put(ctx.workspace_id,'MATERIAL',{'catalog_query_hash':query_hash,'candidates':results},call_id=ctx.call_id,turn_id=ctx.turn_id)
    return catalog_page(results,ref,0,args.limit)


def catalog_page(results,ref,offset,limit):
    selected=results[offset:offset+limit]
    return ToolResult(status='OK' if results else 'EMPTY',data={'candidates':selected,'has_more':len(results)>offset+limit},artifact_refs=[ref],
        next_cursor=ref+'|'+str(offset+limit) if len(results)>offset+limit else None,
        coverage={'complete':len(results)<=offset+limit,'returned':len(selected),'total':len(results),'omissions':[]})


def bound_version(*versions):
    values={value for value in versions if value}
    if len(values)>1:
        raise ValueError('STALE_REFERENCE: conflicting activity versions')
    return next(iter(values),None)


@blocking_tool
def activity(args, ctx):
    explicit_version=bound_version(args.version_ref, args.selector.ref.partition('@')[2] if hasattr(args.selector,'ref') else None)
    query_hash=digest(args.model_dump(mode='json',exclude={'cursor','limit'}))
    if args.cursor:
        ref,_,offset=args.cursor.rpartition('|')
        data=ctx.artifact_port.read(ctx.workspace_id,ref)['payload']
        if data.get('activity_query_hash')!=query_hash or not offset.isdigit():raise ValueError('STALE_REFERENCE: activity cursor does not match query/version')
        if 'activity_selectors' in data:
            return material_page(data['activity_selectors'],ref,int(offset),args,ctx)
        return activity_page(data['activities'],ref,int(offset),args.limit)
    if args.section_refs and all(ref.startswith('artifact:') for ref in args.section_refs):
        section_version=explicit_version
        sections=[ctx.artifact_port.read(ctx.workspace_id,ref) for ref in args.section_refs]
        with ctx.services['knowledge'].read() as session:
            reader=ctx.services['knowledge'].activity_reader(session)
            if hasattr(args.selector,'query'):
                allowed={str(row.id) for row in locate_all(reader,text=args.selector.query)}
            else:
                raw=args.selector.ref
                if raw.startswith('artifact:'):
                    material=ctx.artifact_port.read(ctx.workspace_id,raw)['payload']
                    allowed={material.get('activity_ref',material.get('ref'))}
                    section_version=bound_version(section_version,material.get('version_ref'))
                elif raw.startswith(('program:','tier:')):
                    allowed={str(row.id) for row in locate_all(reader,ref=raw.partition(':')[2])}
                else:allowed={raw.removeprefix('activity:').split('@')[0]}
            version=section_version
            for section in sections:
                value=section['payload']
                if value.get('activity_ref') not in allowed or version and value.get('version_ref')!=version:
                    raise ValueError('Section does not belong to requested activity/version')
        return ToolResult(data={'sections':sections},artifact_refs=args.section_refs,
                          coverage={'complete':True,'returned':len(sections),'total':len(sections),'omissions':[]})
    with ctx.services['knowledge'].read() as s:
        reader=ctx.services['knowledge'].activity_reader(s)
        version=explicit_version
        scoped_versions={}
        if hasattr(args.selector,'ref'):
            raw=args.selector.ref
            if raw.startswith('artifact:'):
                obj=ctx.artifact_port.read(ctx.workspace_id,raw)['payload']
                if 'step_refs' in obj:
                    from journeyplus.agent.services.route_objects import RouteObject
                    steps=list(RouteObject.read(ctx.artifact_port,ctx.workspace_id,raw).steps.values())
                    if version and any(step['version_ref']!=version for step in steps):
                        raise ValueError('Requested version differs from the route snapshot')
                    scoped_versions={UUID(step['activity_ref']):step['version_ref'] for step in steps}
                    identities=list(scoped_versions)
                    raw=None
                else:
                    raw=obj.get('activity_ref',obj.get('ref',''))
                    version=bound_version(version,obj.get('version_ref'))
            if raw is not None and raw.startswith(('program:', 'tier:')):
                identities=[a.id for a in locate_all(reader,ref=raw.partition(':')[2])]
                raw=None
            if raw is not None:
                raw=raw.removeprefix('activity:')
            if raw is not None:
                identity, _, embedded_version=raw.partition('@')
                version=bound_version(version,embedded_version)
                identities=[UUID(identity)]
        else:
            identities=[a.id for a in locate_all(reader,text=args.selector.query)]
        selectors=[]
        for identity in identities:
            selected_version=scoped_versions.get(identity,version) or ctx.services['knowledge'].current_version(s,identity)
            if selected_version:selectors.append({'activity_ref':str(identity),'version_ref':selected_version})
    collection=ctx.artifact_port.put(ctx.workspace_id,'MATERIAL',{'activity_query_hash':query_hash,'activity_selectors':selectors},call_id=ctx.call_id,turn_id=ctx.turn_id)
    return material_page(selectors,collection,0,args,ctx)


def locate_all(reader,**selector):
    rows=[];offset=0
    while True:
        page=reader.locate(**selector,limit=50,offset=offset)
        rows.extend(page[:50])
        if len(page)<=50:return rows
        offset+=50


def material_page(selectors,collection,offset,args,ctx):
    if not 0<=offset<=len(selectors):raise ValueError('Invalid activity cursor offset')
    if args.view=='original':
        if len(selectors)!=1:raise ValueError('Select one activity version before reading its archived document')
        selector=selectors[0]
        with ctx.services['knowledge'].read() as session:
            reader=ctx.services['knowledge'].activity_reader(session)
            material=reader.materials(selector={'ref':selector['activity_ref']},version_ref=selector['version_ref'],
                                      section_refs=args.section_refs)
        return ToolResult(data={'documents':material['data']['documents']},
            coverage={'complete':True,'returned':1,'total':1,'scope':'selected_original_document',
                      'omissions':[]})
    details=[]
    with ctx.services['knowledge'].read() as s:
        reader=ctx.services['knowledge'].activity_reader(s)
        for selector in selectors[offset:offset+args.limit]:
            identity=UUID(selector['activity_ref']);selected_version=selector['version_ref']
            detail=reader.detail(identity,UUID(selected_version) if selected_version else None)
            if 'version_ref' not in detail:
                continue
            detail.setdefault('brief_url',f"/knowledge?activity_id={detail['ref']}&version_ref={detail['version_ref']}&section=brief")
            if args.view=='changes':
                detail['history']=reader.history(identity)
            if args.view=='evidence' or args.aspects or args.section_refs:
                detail['evidence']=reader.materials(selector={'ref':str(identity)},question='',view='EVIDENCE',aspects=[a.upper() for a in args.aspects],section_refs=args.section_refs,version_ref=detail['version_ref'])
            details.append(sectioned(detail))
    refs=[]
    summaries=[]
    for detail in details:
        ref=ctx.artifact_port.put(ctx.workspace_id,'MATERIAL',detail,call_id=ctx.call_id,turn_id=ctx.turn_id)
        refs.append(ref)
        summaries.append(summary(detail,ref,args.view))
    end=min(offset+args.limit,len(selectors))
    return ToolResult(status='OK' if selectors else 'EMPTY',data={'activities':summaries},artifact_refs=[collection,*refs],
        provenance=[{'kind':'workflow','version_ref':item['version_ref']} for item in summaries],
        next_cursor=collection+'|'+str(end) if end<len(selectors) else None,
        coverage={'complete':end==len(selectors),'returned':len(summaries),'total':len(selectors),'offset':offset,'omissions':[]})


def activity_page(summaries,ref,offset,limit):
    selected=summaries[offset:offset+limit]
    return ToolResult(status='OK' if summaries else 'EMPTY',data={'activities':selected},
        artifact_refs=[*[item['material_ref'] for item in selected],ref],
        provenance=[{'kind':'workflow','version_ref':item['version_ref']} for item in selected],
        next_cursor=ref+'|'+str(offset+limit) if len(summaries)>offset+limit else None,
        coverage={'complete':len(summaries)<=offset+limit,'returned':len(selected),'total':len(summaries),'omissions':[]})
