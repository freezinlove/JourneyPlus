import httpx
from journeyplus.agent.harness.contracts import ToolResult


async def read(args,ctx):
    service=ctx.services['research']
    from journeyplus.agent.services.web_projection import binding,page_excerpt
    text_start=link_start=0
    if args.cursor:
        parts=args.cursor.split('|')
        if len(parts)!=4 or parts[3]!=binding(args) or not all(value.isdigit() for value in parts[1:3]):
            raise ValueError('STALE_REFERENCE: page cursor does not match URL and sections')
        ref=parts[0];text_start,link_start=map(int,parts[1:3])
        artifact=ctx.artifact_port.read(ctx.workspace_id,ref)
        if artifact['kind']!='PAGE' or artifact['payload']['url']!=args.url:raise ValueError('Expected this URL page snapshot')
        page=artifact['payload']
    else:
        try:page=await service.page(args.url,args.refresh,30000)
        except PermissionError as exc:return ToolResult.failure('UNAVAILABLE',str(exc),status='UNAVAILABLE')
        except (httpx.HTTPError,OSError,TimeoutError):return ToolResult.failure('SOURCE_UNAVAILABLE','Public source could not be read',retryable=True)
        ref=ctx.artifact_port.put(ctx.workspace_id,'PAGE',page,call_id=ctx.call_id)
    data,coverage,cursor=page_excerpt(page,ref,args,text_start,link_start)
    return ToolResult(status='PARTIAL' if data['truncated'] else 'OK',data=data,artifact_refs=[ref],
                      coverage=coverage,next_cursor=cursor,
                      cache={'hit':page['cache_hit'],'observed_at':page['observed_at']})


async def search(args,ctx):
    try:result=await ctx.services['research'].search(args)
    except PermissionError as exc:return ToolResult.failure('UNAVAILABLE',str(exc),status='UNAVAILABLE')
    except (httpx.HTTPError,OSError,TimeoutError):return ToolResult.failure('SOURCE_UNAVAILABLE','Public source could not be read',retryable=True)
    if result.get('unavailable'):return ToolResult.failure(result['unavailable'],'Search capability is unavailable for this request',status='UNAVAILABLE')
    return ToolResult(status='OK' if result['results'] else 'EMPTY',data=result,next_cursor=result.get('next_cursor'),
                      coverage=result.get('coverage') or {'total':None,'returned':len(result['results']),
                          'complete':False,'scope':'provider_search_page','omissions':['provider_coverage_not_declared']})


async def parse(args,ctx):
    from journeyplus.agent.report_pages import parse_report_detail
    from journeyplus.knowledge.models import MembershipProgram,MembershipTier
    from journeyplus.knowledge.publication import canonical_key
    from sqlalchemy import select
    identities={}
    subjects={}
    with ctx.services['knowledge'].read() as s:
        programs={p.id:p for p in s.scalars(select(MembershipProgram))}
        for tier in s.scalars(select(MembershipTier)):
            program=programs[tier.program_id]
            identities[canonical_key(program.display_name+' '+tier.display_name)]={'program_ref':str(program.id),'tier_ref':str(tier.id)}
        if args.subject:
            for name in ('source','target'):
                value=getattr(args.subject,name)
                if value:subjects[name]=ctx.services['identities'].resolve(s,value,context=ctx)
    reports={};comparisons=[]
    for page_ref in args.page_refs:
        page=ctx.artifact_port.read(ctx.workspace_id,page_ref)
        if page['kind']!='PAGE':raise ValueError('research.parse requires page artifacts')
        data=page['payload']
        report=parse_report_detail(data['raw_html'],data['final_url'],identities).model_dump(mode='json')
        mismatches=[];missing=[];matched=[]
        for role,prefix in [('source','from'),('target','to')]:
            subject=subjects.get(role)
            if not subject or subject['status']!='OK':missing.append(role);continue
            for field in ('program_ref','tier_ref'):
                wanted=subject.get(field);actual=report.get(prefix+'_'+field)
                if not wanted or not actual:missing.append(role+'.'+field)
                elif wanted.partition(':')[2]!=actual:mismatches.append(role+'.'+field)
                else:matched.append(role+'.'+field)
        if args.method and report.get('method') and args.method!=report['method']:mismatches.append('method')
        elif args.method and not report.get('method'):missing.append('method')
        report['identity_matches']={'matched':matched,'missing':missing,'mismatches':mismatches}
        reports[report['report_ref']]=report
        comparisons.append({'report_ref':report['report_ref'],'level':'INCOMPARABLE' if mismatches else 'UNKNOWN' if not matched else 'PARTIAL' if missing else 'EXACT',
                            'reasons':mismatches+missing})
    ref=ctx.artifact_port.put(ctx.workspace_id,'REPORT',{'reports':reports},call_id=ctx.call_id,source_refs=args.page_refs)
    for item in comparisons:item['report_ref']=ref+'#report:'+item['report_ref']
    return ToolResult(data={'report_refs':[ref+'#report:'+key for key in reports], 'reports':list(reports.values()),
                           'comparisons':comparisons},artifact_refs=[ref],
                      coverage={'complete':True,'returned':len(reports),'total':len(reports),'omissions':[]})
