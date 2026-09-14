from journeyplus.agent.harness.execution import blocking_tool
from uuid import UUID, uuid5, NAMESPACE_URL
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.agent.services.presentations import build_block
from .route_objects import RouteObject, RouteReferenceError


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
                if selection.type in {'route_graph','comparison'}:
                    data=RouteObject.read(ctx.artifact_port,ctx.workspace_id,ref).display_data()
                elif ref.startswith('activity:'):
                    identity, separator, version=ref.removeprefix('activity:').partition('@')
                    if not separator:raise ValueError('Published display reference requires a version')
                    with ctx.services['knowledge'].read() as read_session:
                        data=ctx.services['knowledge'].activity_reader(read_session).detail(UUID(identity),UUID(version))
                    data.setdefault('brief_url',f'/knowledge?activity_id={identity}&version_ref={version}&section=brief')
                else:
                    obj=ctx.artifact_port.read(ctx.workspace_id,ref)
                    from .research_pages import resolve_report
                    if selection.type=='experience':obj=resolve_report(obj,ctx)
                    data=obj['payload']
                if selection.type=='mapping_table':
                    if not data.get('version_ref') or 'options' not in data:
                        raise ValueError('Mapping table requires a published activity:UUID@VERSION reference')
                    data={key:data[key] for key in ('ref','version_ref','name','options','brief_url') if key in data}
                    data['options']=[{'mappings':o.get('mappings',[])} for o in data['options'] if o.get('mappings')]
                objects.append(data)
            research=[]
            for ref in selection.research_refs:
                from .research_pages import resolve_report
                related=resolve_report(ctx.artifact_port.read(ctx.workspace_id,ref),ctx)
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
                research.append({'ref':related['ref'],'data':raw,'bindings':bindings})
            block=build_block(selection,objects)
            block['payload']['research']=research
            block['research_bindings']=[binding for item in research for binding in item['bindings']]
            block['id']=str(uuid5(NAMESPACE_URL,ctx.workspace_id+':'+ctx.turn_id+':'+ctx.call_id+':'+str(index)))
            blocks.append(block)
        for step in args.next_steps:
            for ref in step.subject_refs:store.validate_reference(ctx.workspace_id,ref)
        return {'blocks':blocks,'answer':args.answer,'next_steps':[n.model_dump() for n in args.next_steps],'omissions':[]}
    try:
        ref, receipt = store.save_presentation(ctx.workspace_id, ctx.turn_id, ctx.call_id,
                                              args.replace_presentation_ref, build)
    except RouteReferenceError as exc:
        return ToolResult.failure('WRONG_REFERENCE_TYPE',str(exc),candidates=exc.candidates,
            fields=[{'received_ref':exc.ref,'expected':'route', 'matching_route_count':exc.total,
                     'candidates_complete':exc.total==len(exc.candidates),
                     'snapshot_ref':exc.ref.partition('#')[0]}])
    return ToolResult(data={'presentation_ref':ref,**{k:v for k,v in receipt.items() if k!='blocks'},
                           'blocks':[{k:v for k,v in b.items() if k!='payload'} for b in receipt['blocks']]},artifact_refs=[ref])
