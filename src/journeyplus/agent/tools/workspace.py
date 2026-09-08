async def read(args,ctx):
    return await ctx.services['workspace_read'](args,ctx)


async def note(args,ctx):
    return await ctx.services['workspace_note'](args,ctx)
