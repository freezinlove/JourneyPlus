from journeyplus.agent.harness.execution import blocking_tool
@blocking_tool
def manage(args,ctx):
    return ctx.services['waiting'].manage(args,ctx)
