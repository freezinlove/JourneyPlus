"""Shared immutable route-object contract, independent of any tool handler."""
from copy import deepcopy
from dataclasses import dataclass, field


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
            raise ValueError('Expected a computed route member reference')
        root = artifacts.read(workspace_id, root_ref)
        if root['kind'] != 'ROUTES':
            raise ValueError('Expected an immutable computed ROUTES artifact')
        payload = root['payload']
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
                'brief_links':[{'url':f"/knowledge?activity_id={step['activity_ref']}&version_ref={step['version_ref']}&section=brief",
                                'version_ref':step['version_ref'], 'title':step.get('to')}
                               for step in steps.values()]}
