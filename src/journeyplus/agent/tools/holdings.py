from journeyplus.agent.harness.execution import blocking_tool
from journeyplus.agent.harness.contracts import ToolResult


@blocking_tool
def read(args,ctx):
    holdings=ctx.services['user_memory'].read(args)
    ref=ctx.artifact_port.put(ctx.workspace_id,'MATERIAL',{'holdings':holdings},call_id=ctx.call_id,turn_id=ctx.turn_id)
    return ToolResult(status='OK' if holdings else 'EMPTY',
                      data={'holdings':holdings,'snapshot_ref':ref},artifact_refs=[ref],
                      coverage={'complete':True,'returned':len(holdings),'total':len(holdings),'omissions':[]})


@blocking_tool
def write(args,ctx):
    return ctx.services['user_memory'].write(args,ctx)
