"""Check declared deliverables against observations; render exact referenced facts.

This boundary cannot prove that a model captured every natural-language request.
It checks execution and evidence, never chooses a next tool or a recommendation.
"""
import json
from typing import Literal
from pydantic import Field, ValidationError
from journeyplus.agent.harness.contracts import DTO, CompletionCheck


class Fact(DTO):
    ref: str
    path: str = Field(pattern=r'^/')


class Delivery(DTO):
    kind: Literal['presentation', 'operation', 'coverage']
    call_id: str
    type: str | None = None
    columns: list[str] = Field(default_factory=list, max_length=7)
    minimum_objects: int = Field(default=1, ge=1, le=20)


class Answer(DTO):
    status: Literal['complete', 'partial']
    # Text is interpretation. Exact database values use Fact, never copied values.
    parts: list[str | Fact] = Field(min_length=1, max_length=50)
    deliveries: list[Delivery] = Field(default_factory=list, max_length=20)
    remaining: list[str] = Field(default_factory=list, max_length=20)


def pointer(value, path):
    for encoded in path.split('/')[1:]:
        key = encoded.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not key.isdigit():
                raise ValueError('Invalid array index')
            value = value[int(key)]
        else:
            value = value[key]
    return value


class BusinessCompletion:
    version = 'referenced-delivery-v1'

    def check(self, text, messages, context):
        current = [m for m in messages if m.metadata.get('turn_id') == context.turn_id]
        calls = {p.call_id: p for m in current for p in m.content if p.type == 'tool_call'}
        results = {p.call_id: p.result for m in current for p in m.content if p.type == 'tool_result'}
        # Direct conversation remains legal and needs neither a task tool nor a plan.
        if not calls and not text.lstrip().startswith('{'):
            return CompletionCheck(accepted=True)
        try:
            answer = Answer.model_validate_json(text)
        except ValidationError:
            if not calls:
                return CompletionCheck(accepted=True)
            return CompletionCheck(accepted=False, feedback=[
                'Return final JSON {status:"complete"|"partial",parts:[text or {ref,path}],'
                'deliveries:[{kind:"presentation"|"operation"|"coverage",call_id,type?,columns?,minimum_objects?}],'
                'remaining:[]}. Include all user-requested deliveries, not just successful ones. '
                'Use immutable artifact JSON pointers for exact facts. Tool calls remain native.'])
        findings = []
        # Repair may replace a failed call id, but cannot silently weaken a
        # previously declared delivery. Persisted rejected drafts survive resume.
        for message in current:
            if not message.metadata.get('completion_rejected'):
                continue
            for part in message.content:
                if part.type != 'text':
                    continue
                try:
                    previous = Answer.model_validate_json(part.text)
                except (ValidationError, TypeError):
                    continue
                for required in previous.deliveries:
                    if not any(item.kind == required.kind and item.type == required.type
                               and set(item.columns) >= set(required.columns)
                               and item.minimum_objects >= required.minimum_objects for item in answer.deliveries):
                        findings.append('A previously declared delivery was removed or weakened; fulfill it or report partial.')
        if answer.status == 'complete' and answer.remaining:
            findings.append('A complete answer cannot have remaining work.')
        if answer.status == 'partial' and not answer.remaining:
            findings.append('A partial answer must identify remaining work.')
        for delivery in answer.deliveries:
            call, result = calls.get(delivery.call_id), results.get(delivery.call_id)
            if not call or not result or result.get('status') not in {'OK', 'PARTIAL', 'EMPTY'}:
                findings.append(f'{delivery.call_id}: missing successful receipt in this turn.')
                continue
            data = result.get('data', {})
            if delivery.kind == 'presentation':
                if call.name != 'display.present' or not data.get('presentation_ref'):
                    findings.append(f'{delivery.call_id}: not a presentation receipt.')
                    continue
                blocks = data.get('blocks', [])
                if not any((not delivery.type or b.get('type') == delivery.type)
                           and set(delivery.columns) <= set(b.get('columns', []))
                           and b.get('object_count', 0) >= delivery.minimum_objects for b in blocks):
                    findings.append(f'{delivery.call_id}: required presentation type, columns or object count missing.')
            elif delivery.kind == 'operation':
                if call.name not in {'holdings.write', 'waiting.manage'} or not data.get('operation_ref') or data.get('outcome') not in {'APPLIED','NOOP'}:
                    findings.append(f'{delivery.call_id}: no committed operation receipt.')
            elif delivery.kind == 'coverage':
                coverage = result.get('coverage', {})
                if not coverage.get('complete') or result.get('next_cursor'):
                    findings.append(f'{delivery.call_id}: coverage incomplete; unread pages are not knowledge absence.')
                elif call.name == 'routes.evaluate':
                    query_ref = data.get('query_ref')
                    spans = sorted((r.get('coverage',{}).get('offset',0),r.get('coverage',{}).get('returned',0))
                                   for r in results.values() if query_ref and r.get('data',{}).get('query_ref') == query_ref)
                    end = 0
                    for start,count in spans:
                        if start > end:
                            break
                        end = max(end,start+count)
                    if end < coverage.get('total',0):
                        findings.append(f'{delivery.call_id}: missing earlier candidate pages.')
        # A partial response preserves successful effects and explicitly reports
        # unmet delivery checks; it does not need to pretend they succeeded.
        unmet = findings if answer.status == 'partial' and answer.remaining else []
        if unmet:
            findings = []
        rendered = []
        for part in answer.parts:
            if isinstance(part, str):
                rendered.append(part)
                continue
            try:
                record = context.artifact_port.read(context.workspace_id, part.ref)
                if record['kind'] not in {'ROUTES','MATERIAL','REPORT','PAGE'}:
                    raise ValueError('Notes, task interpretations and presentation labels are not source facts')
                value = pointer(record['payload'], part.path)
                # A citation addresses an exact snapshot; no model-provided value exists to override it.
                rendered.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            except (LookupError, ValueError, KeyError, IndexError, TypeError):
                findings.append(f'{part.ref}{part.path}: fact not found in scoped immutable snapshot.')
        if findings:
            return CompletionCheck(accepted=False, feedback=findings[:20])
        output = '\n'.join(rendered)
        if answer.remaining:
            output += '\n\n尚未完成：'+'；'.join([*answer.remaining,*unmet])
        sources=list(dict.fromkeys(part.ref for part in answer.parts if isinstance(part,Fact)))
        ref=context.artifact_port.put_once(context.workspace_id,'RESPONSE',
                                           {'turn_id':context.turn_id,'answer':answer.model_dump(mode='json')},
                                           turn_id=context.turn_id,source_refs=sources)
        return CompletionCheck(accepted=True, text=output, partial=answer.status == 'partial',artifact_refs=[ref])
