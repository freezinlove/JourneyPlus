"""Explicit query provenance; never infer a user's intent from conversation text."""


def validate_changes(ctx,args,lineage):
    """Prevent implicit constraint replacement. Evidence is auditable, not entailment."""
    from journeyplus.agent.harness.contracts import ToolResult
    protected=[change for change in lineage['changes'] if lineage['parent_query_ref']
               and (change['field'] in {'/category','/alliance'} or change['field'].startswith('/constraints/'))]
    declared={item.field:item for item in args.constraint_changes}
    if len(declared)!=len(args.constraint_changes):
        return ToolResult.failure('INVALID_ARGUMENT','Duplicate constraint change fields')
    required={change['field'] for change in protected}
    if set(declared)!=required:
        result=ToolResult.failure('CONSTRAINT_CHANGE_REQUIRED',
            'Changed query filters require explicit per-field user evidence. Preserve the parent query if the user did not change them.')
        result.data={'query_ref':lineage['parent_query_ref'],'query_context':{
                     'changes':protected,'required_fields':sorted(required),
                     'unexpected_fields':sorted(set(declared)-required)}}
        return result
    for field,item in declared.items():
        messages=ctx.authorization_port.history(ctx.workspace_id,refs=[item.message_ref],limit=1)['messages']
        if not any(m['id']==item.message_ref and m['role']=='user' and not m.get('metadata',{}).get('legacy')
                   and item.quote in '\n'.join(p.get('text') or '' for p in m['content'] if p['type']=='text')
                   for m in messages):
            return ToolResult.failure('INVALID_ARGUMENT',f'{field}: change evidence must quote a user message in this workspace')
    lineage['constraint_changes']=[item.model_dump(mode='json') for item in args.constraint_changes]
    for field,item in declared.items():
        lineage['field_origins'][field]={'message_refs':[item.message_ref]}


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
    if args.source_message_refs:
        messages=ctx.authorization_port.history(ctx.workspace_id,refs=args.source_message_refs,limit=20)['messages']
        if {m['id'] for m in messages if m['role']=='user'}!=set(args.source_message_refs):
            raise ValueError('Query evidence must reference user messages in this workspace')
        sources=list(args.source_message_refs)
    else:
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
            'origin_scope':'Field origins identify model-selected user-message evidence, not semantic verification. Initial fields without origins use schema defaults.',
            'inheritance':'Unchanged fields retain parent values. Result endpoints and model prose do not add constraints.'}
