from sqlalchemy import select
from tests.test_knowledge import knowledge_session
from tests.test_knowledge_routes import edge
from journeyplus.knowledge.models import Activity
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.agent.research_targets import disclose_activity_research_steps,resolve_research_targets
from journeyplus.knowledge.references import ReferenceMap


def test_direct_activity_research_needs_no_route_or_holding_and_does_not_inherit_other_query(knowledge_session):
    s=knowledge_session;root,target=edge(s);activity=s.scalars(select(Activity)).first()
    material=ActivityReadService(s).materials(selector={'ref':str(activity.id)},question='申请经验')
    state={'query':{'residency':'CN','source_acquisition':'MATCHED'}}
    subjects=disclose_activity_research_steps(s,state,material)
    assert len(subjects)==1 and not state.get('routes')
    ref=subjects[0]['ref'];result=resolve_research_targets(s,state,[ref])[0]
    assert result.from_tier_ref==str(root) and result.to_tier_ref==str(target)
    assert result.context=={'source_acquisition':'UNKNOWN'}
    references=ReferenceMap(state);packet=references.encode_packet(material)
    assert packet['data']['research_steps'][0]['ref'] in references.entries


def test_activity_research_subjects_have_separate_disclosure_limit(knowledge_session):
    s=knowledge_session;edge(s,alternative=True);activity=s.scalars(select(Activity)).first()
    material=ActivityReadService(s).materials(selector={'ref':str(activity.id)},question='申请经验')
    state={};subjects=disclose_activity_research_steps(s,state,material,limit=1)
    assert len(subjects)==1 and material['coverage']['research_subjects']=={'observed_count':2,'returned_count':1,'has_more':True}
    assert len(state['direct_research_steps'])==1
