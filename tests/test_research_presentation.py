from journeyplus.agent.research_presentation import attach_research
from journeyplus.knowledge.references import ReferenceMap


def test_presentation_keeps_only_selected_step_and_matching_official_version():
    state={'steps':{'a':{'from':'A','to':'B','activity_ref':'activity','version_ref':'v1'},
                    'b':{'from':'B','to':'C','activity_ref':'other','version_ref':'v2'}},
           'current_research_results':[{'data':{'step_observations':[
               {'step_ref':'a','activity_version_ref':'v1','status':'INSUFFICIENT','windows':{},'citations':[]},
               {'step_ref':'b','activity_version_ref':'v2','status':'UNAVAILABLE','windows':{},'citations':[]}]}}]}
    blocks=[{'payload':{'steps':{'a':state['steps']['a']}}}]
    attach_research(blocks,state,ReferenceMap(state))
    assert len(blocks[0]['payload']['research'])==1
    assert blocks[0]['payload']['research'][0]['direction']=='A → B'
    state['steps']['a']['version_ref']='v3';fresh=[{'payload':{'steps':{'a':state['steps']['a']}}}]
    attach_research(fresh,state,ReferenceMap(state))
    assert 'research' not in fresh[0]['payload']
