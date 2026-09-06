"""Presentation-local node groups retain every versioned incoming alternative."""
from journeyplus.knowledge.publication import signature


def presentation_nodes(routes,steps):
    groups={}
    for route in routes:
        for index,ref in enumerate(route['step_refs']):
            step=steps[ref]
            key=('TARGET',step.get('to_tier_id') or step['to'])
            group=groups.setdefault(key,{'name':step['to'],'tier_ref':step.get('to_tier_id'),'kind':'TARGET','step_refs':[]})
            if ref not in group['step_refs']:group['step_refs'].append(ref)
    nodes={}
    for group in groups.values():
        ref=signature({'kind':'PRESENTATION_NODE','routes':[r['ref'] for r in routes],**group})[:16]
        nodes[ref]={'ref':ref,**group}
    return nodes
