from copy import deepcopy
from journeyplus.agent.research_ordering import evidence_order


def sample():
    routes=[{'ref':r,'classification':'MATCH','violations':[],'eligibility':'UNKNOWN','to':'Gold','step_refs':[r]} for r in ['a','unread','b']]
    steps={r['ref']:{'version_ref':'v-'+r['ref']} for r in routes}
    state={'current_question':'哪个证据更充分？','current_research_results':[{'data':{'step_observations':[
        {'step_ref':r,'activity_version_ref':'v-'+r,'status':'COMPLETED','context_hash':'same',
         'windows':{'APPLICATION_12M':{'exact_counts':{'DIRECT_MATCH':count},'unknown_count':999}}}
        for r,count in [('a',1),('b',3)]]}}]}
    return routes,steps,state


def test_step_evidence_dominance_retains_unread_candidate_and_does_not_mutate():
    routes,steps,state=sample();before=deepcopy(routes)
    ordered,basis=evidence_order(routes,steps,state)
    assert [r['ref'] for r in ordered]==['b','unread','a']
    assert routes==before and '不是成功率' in basis['reason']
    assert basis['retained_route_refs']==['a','unread','b']


def test_denials_are_evidence_not_a_false_success_metric():
    routes,steps,state=sample()
    state['current_research_results'][0]['data']['step_observations'][1]['windows']['APPLICATION_12M']['exact_counts']={'DENIED':3}
    ordered,basis=evidence_order(routes,steps,state)
    assert ordered==routes and basis['status']=='NO_COMPARABLE_ADVANTAGE'
    assert not any(k in str(basis).lower() for k in ['probability','success_rate'])


def test_ambiguous_context_old_version_partial_cases_or_explicit_preferences_do_not_reorder():
    for change in ['context','version','window','partial','conflict','official','preference']:
        routes,steps,state=sample();o=state['current_research_results'][0]['data']['step_observations'][1]
        if change=='context':o['context_hash']='different'
        if change=='version':o['activity_version_ref']='old'
        if change=='window':o['windows']={'APPLICATION_DATE_UNKNOWN':o['windows']['APPLICATION_12M']}
        if change=='partial':o['windows']['APPLICATION_12M']['partial_counts']=o['windows']['APPLICATION_12M'].pop('exact_counts')
        if change=='conflict':o['conflict_count']=1
        if change=='official':o['official_recheck_needed']=True
        if change=='preference':state['query']={'preferences':['LOWER_KNOWN_FEE']}
        ordered,basis=evidence_order(routes,steps,state)
        assert ordered==routes and basis['status']=='NO_COMPARABLE_ADVANTAGE',change


def test_investigated_near_miss_cannot_outrank_feasible_route():
    routes,steps,state=sample();routes[0].update(classification='NEARBY',violations=['max_amount'])
    ordered,basis=evidence_order(routes,steps,state)
    assert ordered[-1]['ref']=='a' and len(ordered)==3


def test_multi_step_counts_are_not_pooled():
    routes,steps,state=sample();routes=[routes[0],routes[2]]
    observations=state['current_research_results'][0]['data']['step_observations']
    for route,count in zip(routes,[10,1]):
        ref=route['ref']+'2';route['step_refs'].append(ref);steps[ref]={'version_ref':'v-'+ref}
        observations.append({'step_ref':ref,'activity_version_ref':'v-'+ref,'status':'COMPLETED','context_hash':'same',
            'windows':{'APPLICATION_12M':{'exact_counts':{'DIRECT_MATCH':count}}}})
    # a has (1,10), b has (3,1): neither is stronger at every step.
    ordered,basis=evidence_order(routes,steps,state)
    assert ordered==routes and basis['status']=='NO_COMPARABLE_ADVANTAGE'
