"""Bind bounded experience observations to the answer's official step versions."""
from journeyplus.agent.step_research import research_answer_text


def attach_research(blocks,state,refs):
    observations={o['step_ref']:o for p in state.get('current_research_results',[]) for o in p.get('data',{}).get('step_observations',[])}
    steps={**state.get('direct_research_steps',{}),**state.get('steps',{})}
    for block in blocks:
        payload=refs.decode(block.get('payload',{}))
        allowed=set(payload.get('steps',{}))
        versions={a['version_ref'] for a in payload.get('activities',[])}
        selected=[]
        for ref,observation in observations.items():
            step=steps.get(ref)
            if not step or observation.get('activity_version_ref')!=step['version_ref']:continue
            if ref not in allowed and step['version_ref'] not in versions:continue
            selected.append({**observation,'activity_ref':step['activity_ref'],
                'direction':(step.get('from') or '公开申请')+' → '+step['to'],
                'text':research_answer_text([{'data':{'step_observations':[observation]}}],steps)})
        if selected:block['payload']['research']=refs.encode(selected[:12])
