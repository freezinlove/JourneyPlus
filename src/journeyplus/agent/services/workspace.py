"""History and explicit notes remain data, never execution flags."""
from journeyplus.agent.harness.execution import blocking_tool
from journeyplus.agent.harness.contracts import ToolResult


@blocking_tool
def read(args,ctx):
    if args.kind=='history':
        result=ctx.authorization_port.history(ctx.workspace_id,args.query,args.refs,args.cursor,args.limit)
    elif args.kind in {'notes','presentations'} and not args.refs:
        state=ctx.authorization_port.load_context_index(ctx.workspace_id)['state']
        refs=([state['note_ref']] if state.get('note_ref') else []) if args.kind=='notes' else state['presentation_refs']
        from .artifact_views import view
        result=view([ctx.artifact_port.read(ctx.workspace_id,ref) for ref in refs],cursor=args.cursor,query=args.query,limit=args.limit)
        if args.kind=='notes':result['revision']=state['note_revision']
    elif args.refs:
        from .artifact_views import view
        result=view([ctx.artifact_port.read(ctx.workspace_id,ref) for ref in args.refs],cursor=args.cursor,query=args.query,limit=args.limit)
    else:
        result=ctx.artifact_port.search(ctx.workspace_id,kind={'notes':'NOTE','presentations':'PRESENTATION'}.get(args.kind),
                                       query=args.query,cursor=args.cursor,limit=args.limit)
    count=len(result.get('sections',result.get('artifacts',result.get('messages',[]))))
    return ToolResult(status='PARTIAL' if result.get('next_cursor') else 'OK' if count else 'EMPTY',data=result,next_cursor=result.get('next_cursor'),artifact_refs=args.refs if args.kind!='history' else [],
                      coverage={'complete':not bool(result.get('next_cursor')),'returned':count,
                                'total':result.get('section_count',result.get('total')),'omissions':[]})


@blocking_tool
def note(args,ctx):
    return ctx.authorization_port.save_note(ctx.workspace_id, ctx.turn_id, ctx.call_id,
        args.expected_revision, args.content, args.source_message_refs)
