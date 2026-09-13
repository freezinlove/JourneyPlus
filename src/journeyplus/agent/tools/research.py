from journeyplus.agent.harness.execution import blocking_tool, blocking_call
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
        artifact=await blocking_call(ctx.artifact_port.read,ctx.workspace_id,ref)
        if artifact['kind']!='PAGE' or artifact['payload']['url']!=args.url:raise ValueError('Expected this URL page snapshot')
        page=artifact['payload']
    else:
        try:page=await service.page(args.url,args.refresh,30000)
        except PermissionError as exc:return ToolResult.failure('UNAVAILABLE',str(exc),status='UNAVAILABLE')
        except (httpx.HTTPError,OSError,TimeoutError):return ToolResult.failure('SOURCE_UNAVAILABLE','Public source could not be read',retryable=True)
        ref=await blocking_call(ctx.artifact_port.put,ctx.workspace_id,'PAGE',page,call_id=ctx.call_id,turn_id=ctx.turn_id)
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


@blocking_tool
def parse(args,ctx):
    from journeyplus.agent.report_pages import parse_report_detail,report_body_complete
    reports={};incomplete_pages=[]
    for page_ref in args.page_refs:
        page=ctx.artifact_port.read(ctx.workspace_id,page_ref)
        if page['kind']!='PAGE':raise ValueError('research.parse requires page artifacts')
        data=page['payload']
        report=parse_report_detail(data['raw_html'],data['final_url']).model_dump(mode='json',exclude_none=True)
        page_complete=not data.get('raw_truncated',False)
        body_complete=page_complete or report_body_complete(data['raw_html'])
        report['page_ref']=page_ref
        report['body_complete']=body_complete
        if not page_complete:incomplete_pages.append(page_ref)
        reports[report['report_ref']]=report
    # Full bodies remain in REPORT artifacts for card detail and workspace.read.
    ref=ctx.artifact_port.put(ctx.workspace_id,'REPORT',{'reports':reports},call_id=ctx.call_id,turn_id=ctx.turn_id,source_refs=args.page_refs)
    report_refs=[ref+'#report:'+key for key in reports]
    projected=[];unread=[]
    for report,report_ref in zip(reports.values(),report_refs):
        full=report['text']
        text=full.encode()[:6000].decode(errors='ignore')
        item={**report,'text':text}
        if len(text)<len(full):
            item.update(text_truncated=True,text_characters=len(full),full_text_ref=report_ref)
            unread.append(report_ref)
        projected.append(item)
    result={'report_refs':report_refs,'reports':projected}
    return ToolResult(status='PARTIAL' if incomplete_pages or unread else 'OK',data=result,artifact_refs=[ref],
                      coverage={'complete':not bool(incomplete_pages or unread),'returned':len(reports),'total':len(reports),
                                'omissions':(['source_page_truncated'] if incomplete_pages else [])+(['report_text_continues'] if unread else []),
                                **({'incomplete_page_refs':incomplete_pages} if incomplete_pages else {}),
                                **({'unread_report_refs':unread} if unread else {})})
