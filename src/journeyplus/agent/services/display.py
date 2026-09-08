from journeyplus.agent.harness.execution import blocking_tool
from uuid import UUID, uuid5, NAMESPACE_URL
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.agent.services.presentations import build_block
from .route_objects import RouteObject


@blocking_tool
def present(args,ctx):
    store=ctx.authorization_port
    def build():
        if args.replace_presentation_ref:
            replaced=ctx.artifact_port.read(ctx.workspace_id,args.replace_presentation_ref)
            if replaced['kind']!='PRESENTATION':raise ValueError('Replacement must reference presentation')
        blocks=[]
        for index,selection in enumerate(args.blocks):
            objects=[]
            for ref in selection.object_refs:
                if ref.startswith('activity:'):
                    from journeyplus.knowledge.reads import ActivityReadService
                    identity, separator, version=ref.removeprefix('activity:').partition('@')
                    if not separator:raise ValueError('Published display reference requires a version')
                    with ctx.services['knowledge'].read() as read_session:
                        data=ActivityReadService(read_session).detail(UUID(identity),UUID(version))
                    data['brief_url']=f'/knowledge?activity_id={identity}&version_ref={version}&section=brief'
                else:
                    obj=ctx.artifact_port.read(ctx.workspace_id,ref)
                    data=obj['payload']
                if selection.type in {'route_graph','comparison'}:
                    data=RouteObject.read(ctx.artifact_port,ctx.workspace_id,ref).display_data()
                objects.append(data)
            research=[]
            for ref in selection.research_refs:
                related=ctx.artifact_port.read(ctx.workspace_id,ref)
                if related['kind']!='REPORT':raise ValueError('Research attachment requires parsed reports')
                raw=related['payload'];reports=list(raw['reports'].values()) if 'reports' in raw else [raw]
                bindings=[]
                for report in reports:
                    candidates=[]
                    for obj in objects:
                        for step_ref,step in obj.get('steps',{}).items():
                            comparisons=[(report.get('from_tier_ref'),step.get('from_tier_id')),(report.get('to_tier_ref'),step.get('to_tier_id')),(report.get('to_program_ref'),step.get('target_program_id'))]
                            if any(actual and expected and str(actual)!=str(expected) for actual,expected in comparisons):continue
                            level='EXACT' if all(actual and expected for actual,expected in comparisons) else 'UNKNOWN'
                            candidates.append({'step_ref':step_ref,'identity_level':level})
                    if selection.type in {'route_graph','comparison'} and not candidates:
                        raise ValueError('Research report identities are incompatible with selected route steps')
                    bindings.append({'report_ref':report.get('report_ref'),'compatible_steps':candidates})
                research.append({'ref':ref,'data':raw,'bindings':bindings})
            block=build_block(selection,objects)
            block['payload']['research']=research
            block['research_bindings']=[binding for item in research for binding in item['bindings']]
            block['id']=str(uuid5(NAMESPACE_URL,ctx.workspace_id+':'+ctx.turn_id+':'+ctx.call_id+':'+str(index)))
            blocks.append(block)
        for step in args.next_steps:
            for ref in step.subject_refs:store.validate_reference(ctx.workspace_id,ref)
        return {'blocks':blocks,'next_steps':[n.model_dump() for n in args.next_steps],'omissions':[]}
    ref, receipt = store.save_presentation(ctx.workspace_id, ctx.turn_id, ctx.call_id,
                                          args.replace_presentation_ref, build)
    return ToolResult(data={'presentation_ref':ref,**{k:v for k,v in receipt.items() if k!='blocks'},
                           'blocks':[{k:v for k,v in b.items() if k!='payload'} for b in receipt['blocks']]},artifact_refs=[ref])
