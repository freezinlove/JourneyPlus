"""Shared immutable route-object contract, independent of any tool handler."""
from copy import deepcopy
from dataclasses import dataclass, field


class RouteReferenceError(ValueError):
    """A valid step/snapshot is not a selectable route; expose bounded choices."""
    def __init__(self, ref, candidates, total):
        super().__init__('Select a whole route ref (#route:), not a step or snapshot. No presentation was created.')
        self.ref, self.candidates, self.total = ref, candidates, total


def route_choices(artifacts, workspace_id, ref):
    root_ref, _, fragment = ref.partition('#')
    root = artifacts.read(workspace_id, root_ref)
    if root['kind'] != 'ROUTES':
        return None
    payload = root['payload']
    if fragment and (not fragment.startswith('step:') or fragment[5:] not in payload.get('steps', {})):
        return None
    choices=[]
    for key in payload.get('route_order', sorted(payload.get('routes', {}))):
        route=payload.get('routes', {}).get(key)
        if not route or fragment and fragment[5:] not in route.get('step_refs', []):
            continue
        ids=route.get('step_refs', [])
        if not ids or any(sid not in payload.get('steps', {}) for sid in ids):
            continue
        steps=[payload['steps'][sid] for sid in ids]
        choices.append({'ref':root_ref+'#route:'+key, 'object_type':'route',
                        'path':[steps[0].get('from'), *[step.get('to') for step in steps]]})
    return choices[:10], len(choices)


@dataclass(frozen=True)
class RouteObject:
    ref: str
    root_ref: str
    route: dict
    steps: dict
    query_ref: str | None = None
    resolution: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)

    @classmethod
    def read(cls, artifacts, workspace_id, ref):
        root_ref, separator, fragment = ref.partition('#')
        if not separator or not fragment.startswith('route:'):
            if ref.startswith('artifact:') and (not separator or fragment.startswith('step:')):
                choices=route_choices(artifacts,workspace_id,ref)
                if choices is not None:
                    raise RouteReferenceError(ref,*choices)
            raise ValueError('Expected a computed route member reference')
        root = artifacts.read(workspace_id, root_ref)
        if root['kind'] != 'ROUTES':
            raise ValueError('Expected an immutable computed ROUTES artifact')
        payload = root['payload']
        from journeyplus.knowledge.simple_matching import POLICY
        if payload.get('matching_policy') != POLICY:
            raise LookupError('Matching result expired; query again using current simple matching rules')
        route = payload.get('routes', {}).get(fragment.removeprefix('route:'))
        if route is None:
            raise LookupError('Route does not exist in this snapshot')
        ids = route.get('step_refs')
        if not ids or any(key not in payload.get('steps', {}) for key in ids):
            raise ValueError('Route snapshot is missing its ordered steps')
        return cls(ref, root_ref, deepcopy(route),
                   {key: deepcopy(payload['steps'][key]) for key in ids}, payload.get('query_ref'),
                   deepcopy(payload.get('resolution',{})),deepcopy(payload.get('coverage',{})))

    def display_data(self):
        steps = {self.root_ref+'#step:'+key: {**deepcopy(step), 'ref':self.root_ref+'#step:'+key}
                 for key, step in self.steps.items()}
        return {**deepcopy(self.route), 'ref':self.ref, 'steps':steps,
                'step_refs':list(steps),
                'brief_links':[{'url':step.get('brief_url') or f"/knowledge?activity_id={step['activity_ref']}&version_ref={step['version_ref']}&section=brief",
                                'version_ref':step['version_ref'], 'title':step.get('to')}
                               for step in steps.values()]}
