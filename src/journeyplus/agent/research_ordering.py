"""Conservative evidence ordering, never an estimate of approval probability."""
from collections import defaultdict
import re


def evidence_order(routes, steps, state):
    if not re.search(r'哪.{0,12}更|更稳|比较.{0,12}经验|证据|成功率',state.get('current_question','')):
        return routes,None
    observations={o['step_ref']:o for p in state.get('current_research_results',[])
                  for o in p.get('data',{}).get('step_observations',[])}
    if not observations:return routes,None
    # Near misses remain visible, but cannot outrank a feasible candidate just
    # because the model selected an investigated near miss first.
    routes=sorted(routes,key=lambda r:r['classification']!='MATCH')
    groups=defaultdict(list);profiles={};included=[]
    for index,route in enumerate(routes):
        if route['classification']!='MATCH' or route.get('violations'):continue
        counts=[];contexts=[]
        for ref in route['step_refs']:
            step=steps[ref];observation=observations.get(ref,{})
            if (observation.get('activity_version_ref')!=step['version_ref'] or
                observation.get('status') not in {'COMPLETED','PARTIAL'} or
                observation.get('official_recheck_needed') or observation.get('conflict_count') or
                not observation.get('context_hash')):break
            window=observation.get('windows',{}).get('APPLICATION_12M',{})
            outcomes=window.get('exact_counts',{})
            # Mixed or denied outcomes call for inspection; a larger set of
            # refusals must never promote a route as a recommendation.
            if outcomes.get('DENIED') or (outcomes.get('DIRECT_MATCH') and outcomes.get('CHALLENGE')):break
            known=sum(outcomes.get(k,0) for k in ('DIRECT_MATCH','CHALLENGE'))
            if not known:break
            counts.append(known);contexts.append((observation['context_hash'],'CHALLENGE' if outcomes.get('CHALLENGE') else 'DIRECT_MATCH'))
        else:
            if not counts:continue
            # Different contexts, route lengths and explicit non-evidence
            # preferences must not be flattened into an invented common score.
            if state.get('query',{}).get('preferences'):continue
            key=(route.get('to'),route.get('eligibility'),tuple(contexts))
            groups[key].append(index);profiles[index]=counts;included.append(route['ref'])
    result=list(routes);changed=False
    for indices in groups.values():
        remaining=list(indices);ordered=[]
        while remaining:
            def dominates(a,b):
                return all(x>=y for x,y in zip(profiles[a],profiles[b])) and any(x>y for x,y in zip(profiles[a],profiles[b]))
            # Stable topological ordering of per-step evidence coverage. No sum,
            # ratio or multiplication across steps, and no removal of candidates.
            chosen=next(i for i in remaining if not any(dominates(j,i) for j in remaining))
            ordered.append(chosen);remaining.remove(chosen)
        for slot,source in zip(indices,ordered):result[slot]=routes[source]
        changed|=ordered!=indices
    return result,{'status':'EVIDENCE_ORDERED' if changed else 'NO_COMPARABLE_ADVANTAGE',
        'window':'APPLICATION_12M','eligible_route_refs':included,
        'retained_route_refs':[r['ref'] for r in routes],
        'reason':('已在满足查询条件的同情境候选中，按各步骤近期可比证据的充分程度排序；这不是成功率排名。' if changed else
                  '现有经验不足以改变候选顺序；不同窗口、情境或未调查的候选不能按正面案例数量比较成功率。'),
        'limitations':['仅比较已调查且所有步骤均有近期精确可比案例的子集。','未调查或证据不足的候选保留原位置。','用户明确的费用、步骤或未知条件偏好优先。']}
