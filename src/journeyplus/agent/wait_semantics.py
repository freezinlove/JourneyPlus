"""Waiting notification identity excludes presentation refs and observation times."""
from uuid import UUID
from journeyplus.knowledge.models import ApplicationOptionVersion,OptionMapping,ActivityKnowledgeVersion
from journeyplus.knowledge.publication import signature,_semantic


def material_route_signature(session,route,steps):
    def clean(value):
        if isinstance(value,dict):
            return {k:clean(v) for k,v in value.items() if k not in {'ref','evidence_refs','condition_ref','actual'}}
        if isinstance(value,list):
            return sorted((clean(v) for v in value),key=signature)
        return value
    parts=[]
    for ref in route['step_refs']:
        step=steps[ref]
        option=session.get(ApplicationOptionVersion,UUID(step['option_ref']))
        mapping=session.get(OptionMapping,UUID(step['mapping_ref']))
        version=session.get(ActivityKnowledgeVersion,UUID(step['version_ref']))
        parts.append({'option_identity':str(option.option_id),'mapping_key':mapping.semantic_key,
            'from':step['from_tier_id'],'to':step['to_tier_id'],'method':option.method,
            'conditions':clean(_semantic({'activity':version.facts.get('conditions',{}),'option':option.conditions,'mapping':mapping.conditions})),
            'window':_semantic(option.application_window),'validity':_semantic(option.status_validity),
            'challenge':_semantic(option.challenge),'cost':clean({key:step[key] for key in ('fees','conditional_items','alternative_items','fee_unknown')}),
            'eligibility':step['eligibility'],'availability':step['availability']})
    return signature(parts)
