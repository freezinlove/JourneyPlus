from journeyplus.agent.harness.execution import blocking_call
import httpx
from journeyplus.agent.harness.contracts import ToolResult


async def read(args,ctx):
    service=ctx.services['research']
    from journeyplus.agent.services.web_projection import binding,page_excerpt
    from journeyplus.agent.services.research_pages import save_page
    text_start=link_start=0
    report=None
    if args.cursor:
        parts=args.cursor.split('|')
        if len(parts)!=4 or parts[3]!=binding(args) or not all(value.isdigit() for value in parts[1:3]):
            raise ValueError('STALE_REFERENCE: page cursor does not match URL and sections')
        ref=parts[0];text_start,link_start=map(int,parts[1:3])
        artifact=await blocking_call(ctx.artifact_port.read,ctx.workspace_id,ref)
        if artifact['kind']!='PAGE' or artifact['payload']['url']!=args.url:raise ValueError('Expected this URL page snapshot')
        page=artifact['payload']
        if page.get('report_ref'):
            saved=await blocking_call(ctx.artifact_port.read,ctx.workspace_id,page['report_ref'])
            report=saved['payload']
    else:
        try:page=await service.page(args.url,args.refresh,30000)
        except PermissionError as exc:return ToolResult.failure('UNAVAILABLE',str(exc),status='UNAVAILABLE')
        except (httpx.HTTPError,OSError,TimeoutError):return ToolResult.failure('SOURCE_UNAVAILABLE','Public source could not be read',retryable=True)
        ref,page,report=await blocking_call(save_page,page,ctx)
    data,coverage,cursor=page_excerpt(page,ref,args,text_start,link_start,report=report)
    return ToolResult(status='PARTIAL' if data['truncated'] else 'OK',data=data,artifact_refs=[ref]+([page['report_ref']] if page.get('report_ref') else []),
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
