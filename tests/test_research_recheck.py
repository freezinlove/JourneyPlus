from journeyplus.agent.research_recheck import recheck_official_materials
from journeyplus.agent.step_research import research_decision_packet


def test_recheck_reads_each_activity_once_and_preserves_unreviewed_status():
    calls=[]
    def read(step):
        calls.append(step['activity_ref']);return {'status':'OK','data':{'activities':[{'ref':step['activity_ref'],'version_ref':'new'}]}}
    observations=[{'step_ref':str(i),'citations':[{'evidence_excerpt':'Matched status is not accepted.'}]} for i in range(4)]
    steps={str(i):{'activity_ref':str(i//2),'version_ref':'old'} for i in range(4)}
    packet={'data':{'step_observations':observations}};cache={}
    recheck_official_materials(packet,steps,read,cache,limit=1)
    assert calls==['0']
    assert observations[0]['official_recheck_status']=='FACTS_READ_REQUIRES_REVIEW'
    assert observations[1]['official_recheck_version_changed']
    assert observations[2]['official_recheck_status']=='PENDING_BUDGET'
    assert steps['0']['version_ref']=='old'


def test_signal_after_display_citation_limit_still_triggers_official_read():
    reports=[{'report_ref':str(i),'url':f'https://statusmatcher.com/report/{i}','normalized_outcome':'UNKNOWN','evidence_excerpt':'I uploaded a screenshot.'} for i in range(4)]
    reports[-1]['evidence_excerpt']='I was required to fly four segments.'
    packet=research_decision_packet({'status':'COMPLETED','steps':[{'step_ref':'s','reports':reports}]})
    observation=packet['data']['step_observations'][0]
    assert len(observation['citations'])==3 and observation['official_recheck_needed']
