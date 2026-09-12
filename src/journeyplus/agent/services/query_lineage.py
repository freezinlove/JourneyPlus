"""Explicit query provenance; never infer a user's intent from conversation text."""


def differences(before,after,prefix=''):
    changes=[]
    for key in sorted(set(before)|set(after)):
        old,new=before.get(key),after.get(key)
        path=prefix+'/'+key
        if isinstance(new,dict) and (old is None or isinstance(old,dict)):
            changes.extend(differences(old or {},new,path))
        elif old!=new:changes.append({'field':path,'before':old,'after':new})
    return changes


def read_context(artifacts,workspace,query_record):
    for ref in query_record.get('source_refs',[]):
        item=artifacts.read(workspace,ref)
        if item['kind']=='QUERY_CONTEXT':return item['payload']
    return {}


def build(ctx,args,query,previous=None):
    sources=ctx.authorization_port.user_message_refs(ctx.workspace_id,ctx.turn_id)
    before=previous['payload'] if previous else {}
    ancestry=read_context(ctx.artifact_port,ctx.workspace_id,previous) if previous else {}
    changes=differences(before,query)
    if previous is None:
        explicit=args.query.model_dump(mode='json',exclude_unset=True)
        selected={c['field'] for c in differences({},explicit)}
        changes=[c for c in changes if c['field'] in selected]
    origins=dict(ancestry.get('field_origins',{}))
    for change in changes:
        origins={k:v for k,v in origins.items() if not k.startswith(change['field']+'/')}
        origins[change['field']]={'message_refs':sources}
    return {'parent_query_ref':args.query_ref if previous else None,'source_message_refs':sources,
            'changes':changes,'field_origins':origins,
            'origin_scope':'Field origins record the user turn during which the model set each value, not semantic authorization or extraction provenance. Initial fields without origins use schema defaults.',
            'inheritance':'Unchanged fields retain parent values. Result endpoints and model prose do not add constraints.'}
