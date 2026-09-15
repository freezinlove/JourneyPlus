"""Pure builders preserve model-selected order and immutable version links."""
from copy import deepcopy


def compact_graph_selection(selection, objects):
    """Select whole real paths; never invent edges while merging query results."""
    from types import SimpleNamespace
    from journeyplus.knowledge.simple_matching import highest_targets
    pairs = list(dict(zip(selection.object_refs, objects)).items())
    nodes, best, sources = {}, {}, {}
    for ref, obj in pairs:
        if not obj.get('step_refs') or not obj.get('steps') or not isinstance(obj.get('paid'),bool):
            raise ValueError('Selected object is not a computed route with ordered steps')
        for source in obj.get('query_sources', []):
            sources[source.get('tier_ref') or (source.get('program_name'), source.get('tier_name'))] = source
        last = obj['steps'][obj['step_refs'][-1]]
        target = last['to_tier_id']
        nodes[target] = SimpleNamespace(program_key=last.get('target_program_key', last.get('target_program_id', target)),
            tier_key=last.get('target_tier_key', target))
        score = (len(obj['step_refs']), obj['paid'], ref)
        if target not in best or score < best[target][0]:
            best[target] = (score, ref)
    targets, _ = highest_targets(nodes, list(nodes))
    refs = {best[target][1] for target in targets}
    chosen = [(ref, deepcopy(obj)) for ref, obj in pairs if ref in refs]
    # Only suppress actual whole prefixes, not unrelated paths which happen
    # to share an endpoint. Necessary lower-tier intermediate nodes stay.
    def identities(obj):
        steps = [obj['steps'][sid] for sid in obj['step_refs']]
        return [steps[0]['from_tier_id'], *[s['to_tier_id'] for s in steps]]
    chosen = [(ref, obj) for ref, obj in chosen if not any(
        len(obj['step_refs']) < len(other['step_refs']) and
        identities(obj) == identities(other)[:len(obj['step_refs'])+1]
        for _, other in chosen)]
    for _, obj in chosen:
        obj['query_sources'] = list(sources.values())
    refs = [ref for ref, _ in chosen]
    selection = selection.model_copy(update={'object_refs': refs,
        'roles': [role for role in selection.roles if role.ref in refs]})
    return selection, [obj for _, obj in chosen]


def build_block(selection, objects):
    if selection.type == 'route_graph':
        selection, objects = compact_graph_selection(selection, objects)
    payload={'objects':[]}
    links=[]
    for ref,obj in zip(selection.object_refs,objects):
        value=deepcopy(obj)
        if selection.type in {'route_graph','comparison'}:
            if not value.get('step_refs') or not isinstance(value.get('paid'),bool):
                raise ValueError('Selected object is not a computed route')
        if selection.type=='activity_card' and not value.get('version_ref'):
            raise ValueError('Activity card requires a published version')
        if value.get('brief_url'):
            links.append({'object_ref':ref,'url':value['brief_url'],'version_ref':value['version_ref']})
        if selection.type=='comparison':
            value['comparison_values']={column:[{'step_ref':ref,'version_ref':step['version_ref'],
                'label':str(index+1)+' · '+str(step.get('to') or ''),
                'value':deepcopy(step.get({'window':'application_window','validity':'status_validity','conditions':'constraint_checks'}[column]))}
                for index,(ref,step) in enumerate(value.get('steps',{}).items())]
                for column in selection.columns if column in {'window','validity','conditions'}}
        payload['objects'].append({'ref':ref,'data':value})
    return {'object_count':len(objects),'type':selection.type,'title':selection.title,'reason':selection.reason,
            'ordered_refs':selection.object_refs,'roles':[r.model_dump() for r in selection.roles],
            'columns':selection.columns,'labels':[obj.get('name',obj.get('title',obj.get('to',''))) for obj in objects],'links':links,'payload':payload}
