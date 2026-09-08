"""History and explicit notes remain data, never execution flags."""
from uuid import UUID
from journeyplus.models import AgentInteraction
from journeyplus.agent.harness.contracts import ToolResult


async def read(args,ctx):
    if args.kind=='history':
        result=ctx.authorization_port.history(ctx.workspace_id,args.query,args.refs,args.cursor,args.limit)
    elif args.kind in {'notes','presentations'} and not args.refs:
        state=ctx.authorization_port.load_context_index(ctx.workspace_id)['state']
        refs=([state['note_ref']] if state.get('note_ref') else []) if args.kind=='notes' else state['presentation_refs']
        from .artifact_views import view
        result=view([ctx.artifact_port.read(ctx.workspace_id,ref) for ref in refs],cursor=args.cursor,query=args.query)
        if args.kind=='notes':result['revision']=state['note_revision']
    elif args.refs:
        from .artifact_views import view
        result=view([ctx.artifact_port.read(ctx.workspace_id,ref) for ref in args.refs],cursor=args.cursor,query=args.query)
    else:
        result=ctx.artifact_port.search(ctx.workspace_id,kind={'notes':'NOTE','presentations':'PRESENTATION'}.get(args.kind),
                                       query=args.query,cursor=args.cursor,limit=args.limit)
    count=len(result.get('sections',result.get('artifacts',result.get('messages',[]))))
    return ToolResult(status='PARTIAL' if result.get('next_cursor') else 'OK' if count else 'EMPTY',data=result,next_cursor=result.get('next_cursor'),artifact_refs=args.refs if args.kind!='history' else [],
                      coverage={'complete':not bool(result.get('next_cursor')),'returned':count,
                                'total':result.get('section_count',result.get('total')),'omissions':[]})


async def note(args,ctx):
    store=ctx.authorization_port
    with store.factory.begin() as s:
        workspace=store.workspace(s,ctx.workspace_id,True)
        state=dict(workspace.state)
        if state['note_revision']!=args.expected_revision:
            return ToolResult.failure('CONFLICT','Note revision changed')
        if args.source_message_refs:
            found=store.history(ctx.workspace_id,refs=args.source_message_refs,limit=30)['messages']
            if set(args.source_message_refs)-{m['id'] for m in found}:raise ValueError('Note source reference missing')
        ref=ctx.artifact_port.put_in(s,ctx.workspace_id,'NOTE',{'content':args.content,'source_message_refs':args.source_message_refs,
            'revision':args.expected_revision+1},call_id=ctx.call_id)
        state.update(note_revision=args.expected_revision+1,note_ref=ref)
        workspace.state=state
    return ToolResult(data={'revision':args.expected_revision+1,'note_ref':ref},artifact_refs=[ref])
