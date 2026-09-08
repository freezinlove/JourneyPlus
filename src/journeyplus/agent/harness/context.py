"""Bounded projections retain call/result groups and expose history references."""
import json
from .budget import estimate
from .contracts import ModelMessage, Part


class ContextCapacityError(ValueError):
    """Evidence cannot safely fit; retain it and stop without a lossy rewrite."""


def project(messages, definitions, capabilities, *, note=None, focus=None, reserved_output=2048):
    limit = min(32000, capabilities.context_window-reserved_output-1024)
    schema_tokens = estimate([{'name': d.name, 'description': d.description, 'parameters': d.input_schema} for d in definitions])
    if schema_tokens >= min(8000, limit):
        raise ContextCapacityError('Tool definitions exceed context budget')
    system = [m for m in messages if m.role == 'system']
    conversation = [m.model_copy(deep=True) for m in messages if m.role != 'system']
    # Keep original call/result pairs and their evidence. The previous archive
    # index discarded qualifiers and combined unrelated results into an implicit
    # last-query summary. Until a lossless projection contract is verified,
    # budget old whole turns through the recoverable history window below.
    additions = {}
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
        additions['history_access'] = 'Earlier messages and authorization quotes remain retrievable through the registered history capability.'
    if additions:
        system.append(ModelMessage(role='system', content=[Part(type='text', text=json.dumps(additions, ensure_ascii=False))]))
    if used > limit:
        raise ContextCapacityError('Current tool-call group exceeds context window; full results remain retrievable')
    return system + selected


def bounded_result(result, full_ref, max_bytes=12000):
    """Prune complete entries only; immutable full result is always retrievable."""
    result = result.model_copy(deep=True)
    result.artifact_refs = list(dict.fromkeys([*result.artifact_refs, full_ref]))
    def size():
        return len(result.model_dump_json().encode())
    omitted = []
    target_bytes=max_bytes-768
    while size() > target_bytes:
        choices = []
        def collect(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    collect(item, path+[key])
            elif isinstance(value, list) and value:
                # An entry is atomic: never remove a fee component, path node or
                # step reference inside it and leave a misleading partial object.
                if len(value) > 1:
                    choices.append((len(path), len(json.dumps(value, ensure_ascii=False, default=str)), value, path))
        collect(result.data, [])
        if not choices:
            break
        _, _, values, path = max(choices, key=lambda item:(-item[0], item[1]))
        values.pop()
        omitted.append('.'.join('*' if item.isdigit() else item for item in path))
    if size() > target_bytes:
        omitted.append('data')
        indexes={key:[{**{k:v for k,v in item.items() if
                           (isinstance(v,(str,int,float,bool)) or v is None) and
                           len(json.dumps(v,ensure_ascii=False).encode())<=300},
                       'projection':'index_only','full_result_ref':full_ref}
                      for item in values if isinstance(item,dict)]
                 for key,values in result.data.items() if isinstance(values,list)}
        result.data = {**indexes,**{k:v for k,v in result.data.items() if
                         (isinstance(v,(str,int,float,bool)) or v is None) and
                         len(json.dumps(v,ensure_ascii=False).encode()) <= 300},
                       'summary': 'Full result exceeds model projection; read the referenced artifact.', 'full_result_ref': full_ref}
    if omitted:
        result.coverage = {**result.coverage, 'complete':False, 'omissions':list(dict.fromkeys(omitted)), 'full_result_ref':full_ref}
    if size() > max_bytes:
        from .contracts import ToolResult
        result = ToolResult(call_id=result.call_id,status=result.status,
            error={'code':result.error.code,'message':result.error.message[:200]} if result.error else None,
            data={**{key:value for key,value in result.data.items() if isinstance(value,(str,int,float,bool)) and len(str(value))<=100},
                  'summary':'Full result exceeds projection; expand the referenced artifact.','full_result_ref':full_ref},
            next_cursor=result.next_cursor,artifact_refs=[full_ref],
            coverage={'total':result.coverage.get('total'),'returned':0,'complete':False,'omissions':['full_result'],'full_result_ref':full_ref})
    return result
