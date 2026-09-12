"""Bounded projections retain call/result groups and expose history references."""
import json
from .budget import estimate
from .contracts import ModelMessage, Part

CONTEXT_POLICY_VERSION = 'pressure-only-views-v5-explicit-result-root'


class ContextCapacityError(ValueError):
    """Evidence cannot safely fit; retain it and stop without a lossy rewrite."""


def project(messages, definitions, capabilities, *, note=None, focus=None, reserved_output=2048):
    limit = min(32000, capabilities.context_window-reserved_output-1024)
    schema_tokens = estimate([{'name': d.name, 'description': d.description, 'parameters': d.input_schema} for d in definitions])
    if schema_tokens >= min(8000, limit):
        raise ContextCapacityError('Tool definitions exceed context budget')
    system = [m for m in messages if m.role == 'system']
    conversation = [m.model_copy(deep=True) for m in messages if m.role != 'system']
    # Original messages and full results remain immutable in persistence.
    # Only older-turn model views may become explicitly expandable indexes.
    additions = {}
    availability={d.name:d.availability() for d in definitions if d.availability}
    if availability:additions['capability_availability']=availability
    if note:
        additions['model_authored_note'] = note
    if focus:
        additions['user_selected_focus'] = focus
    # Never cut a user turn between its assistant calls and tool results.
    groups = []
    for message in conversation:
        if message.role == 'user' or not groups:
            groups.append([])
        groups[-1].append(message)
    definitions_by_name={definition.name:definition for definition in definitions}
    seen={}
    for group in reversed(groups):
        names={p.call_id:p.name for m in group for p in m.content if p.type=='tool_call'}
        for message in reversed(group):
            for part in message.content:
                if part.type!='tool_result' or not part.result:continue
                definition=definitions_by_name.get(names.get(part.call_id))
                raw=part.result
                if not definition or definition.effect!='READ' or definition.operation_effects or raw.get('error'):continue
                # Same data, effective parameters, coverage and source versions
                # only. Different snapshots or mutations are never deduplicated.
                stable={k:v for k,v in raw.items() if k not in {'call_id','metrics','cache','artifact_refs'}}
                stable['coverage']={k:v for k,v in raw.get('coverage',{}).items() if k!='full_result_ref'}
                signature=json.dumps(stable,sort_keys=True,ensure_ascii=False)
                full_ref=raw.get('coverage',{}).get('full_result_ref') or next((r for r in reversed(raw.get('artifact_refs',[])) if r.startswith('artifact:')),None)
                if signature in seen and full_ref and len(signature)>1500:
                    part.result={**raw,'data':{'context_projection':'duplicate_read','same_result_as_message':seen[signature],
                                             'full_result_ref':full_ref},
                        'coverage':{**raw.get('coverage',{}),'complete':False,'omissions':['duplicate_body_available_by_reference']}}
                else:seen[signature]=message.id
    current_pressure=(schema_tokens+estimate([m.model_dump(mode='json') for m in system+conversation])+estimate(additions)
                      >min(24000,limit))
    for index,group in enumerate(groups):
        call_names={part.call_id:part.name for message in group for part in message.content if part.type=='tool_call'}
        latest_calls=next(({p.call_id for p in m.content if p.type=='tool_call'} for m in reversed(group)
                           if any(p.type=='tool_call' for p in m.content)),set())
        for message in group:
            for part in message.content:
                if part.type!='tool_result' or not part.result:continue
                raw=part.result
                full_ref=raw.get('coverage',{}).get('full_result_ref') or next(
                    (ref for ref in reversed(raw.get('artifact_refs',[])) if ref.startswith('artifact:')),None)
                # Latest observation stays fully available. Earlier observations
                # in this turn can use the tool's atomic expandable projection.
                current=index==len(groups)-1
                if current and (not current_pressure or part.call_id in latest_calls):continue
                capacity=6000 if current else 3000
                if full_ref and not raw.get('error') and len(json.dumps(raw,ensure_ascii=False).encode())>capacity:
                    from .contracts import ToolResult
                    definition=definitions_by_name.get(call_names.get(part.call_id))
                    view=bounded_result(ToolResult.model_validate(raw),full_ref,capacity,
                                        trim=definition.trim_projection if definition else None)
                    view.data['context_projection']='expand full_result_ref before relying on omitted facts; persisted original is unchanged'
                    part.result=view.model_dump(mode='json')
    selected = []
    def visible_count(items):
        return sum(message.role == 'user' or
                   message.role == 'assistant' and
                   not message.metadata.get('context_projection') and
                   not any(part.type == 'tool_call' for part in message.content) and
                   any(part.type == 'text' and part.text for part in message.content)
                   for message in items)
    used = schema_tokens + estimate([m.model_dump(mode='json') for m in system]) + estimate(additions)
    omitted = False
    for group in reversed(groups):
        size = estimate([m.model_dump(mode='json') for m in group])
        if selected and (used + size > min(24000, limit) or visible_count(selected)+visible_count(group)>12):
            omitted = True
            break
        selected[0:0] = group
        used += size
    if omitted:
        additions['history_available_before'] = selected[0].id
        additions['history_access'] = 'Earlier messages remain retrievable through the registered history capability.'
    if additions:
        system.append(ModelMessage(role='system', content=[Part(type='text', text=json.dumps(additions, ensure_ascii=False))]))
    if used > limit:
        raise ContextCapacityError('Current tool-call group exceeds context window; full results remain retrievable')
    return system + selected


def bounded_result(result, full_ref, max_bytes=12000, *, trim=None):
    """Keep atomic evidence; tools declare relationships between their row arrays."""
    result=result.model_copy(deep=True)
    result.artifact_refs=list(dict.fromkeys([*result.artifact_refs,full_ref]))
    original_coverage=dict(result.coverage)
    # Source/member references and the stored ToolResult have different shapes.
    # Always identify the exact root of the visible data for field citations.
    result.coverage['full_result_ref']=full_ref
    result.coverage['data_path']='/data'
    # A trimmed page embeds its original coverage and retrieval pointers below.
    # Reserve their actual size before trimming; the fixed 768-byte reserve
    # could overflow after adding metadata and erase every retained candidate.
    target=max_bytes-max(768,len(json.dumps(original_coverage,ensure_ascii=False).encode())+len(full_ref)*4+512)
    omitted=False
    def size():return len(result.model_dump_json().encode())
    def generic_trim(value):
        # Only a single top-level array is unambiguous without domain knowledge.
        arrays=[item for item in value.data.values() if isinstance(item,list)]
        if len(arrays)!=1 or len(arrays[0])<=1:return None
        arrays[0].pop()
        return len(arrays[0])
    trimmer=trim or generic_trim
    while size()>target:
        count=trimmer(result)
        if count is None:break
        omitted=True
        result.coverage['returned']=count
        if 'returned_count' in result.coverage:result.coverage['returned_count']=count
    if size()>target:
        # Scalar facts and identifiers survive in an explicitly incomplete index.
        # Never present a pruned before/after, route or report as complete evidence.
        indexes={key:[{**{field:value for field,value in row.items() if (field=='ref' or field.endswith('_ref'))
                           and isinstance(value,str) and len(value)<=300},'projection':'index_only'}
                      for row in values if isinstance(row,dict)]
                 for key,values in result.data.items() if isinstance(values,list)}
        result.data={**indexes,**{key:value for key,value in result.data.items()
                     if (isinstance(value,(str,int,float,bool)) or value is None)
                     and len(json.dumps(value,ensure_ascii=False).encode())<=300}}
        result.data.update(projection='index_only',full_result_ref=full_ref,
                           summary='Read the full result artifact for evidence and source pagination.')
        result.coverage['returned']=0
        if 'returned_count' in result.coverage:result.coverage['returned_count']=0
        omitted=True
    if omitted:
        result.coverage.update(complete=False,retrieval_complete=False,
            source_page_coverage=original_coverage,
            omissions=list(dict.fromkeys([*original_coverage.get('omissions',[]),'model_projection_entries'])),
            full_result_ref=full_ref)
        result.data['full_result_ref']=full_ref
        if result.next_cursor:
            result.coverage['source_next_cursor']=result.next_cursor
            result.next_cursor=None
        # A nested cursor must not skip unread rows of the current source page.
        if result.data.get('next_cursor'):
            result.coverage['source_next_cursor']=result.data.pop('next_cursor')
    if size()>max_bytes:
        from .contracts import ToolResult
        result=ToolResult(call_id=result.call_id,status=result.status,
            error={'code':result.error.code,'message':result.error.message[:200]} if result.error else None,
            data={**{key:value for key,value in result.data.items() if isinstance(value,(str,int,float,bool)) and len(str(value))<=100},
                  'projection':'index_only','full_result_ref':full_ref},artifact_refs=[full_ref],
            coverage={'complete':False,'returned':0,'total':original_coverage.get('total'),
                      'omissions':['full_result'],'full_result_ref':full_ref})
    return result
