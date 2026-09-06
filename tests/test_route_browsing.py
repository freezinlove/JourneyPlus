from copy import deepcopy
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,func
from tests.test_workspace import factory
from tests.test_knowledge_routes import edge
from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
from journeyplus.agent.workspace_models import WorkspaceMessage,WorkspaceTurn
from journeyplus.agent.route_browsing import browse_routes
from journeyplus.knowledge.references import ReferenceMap
from journeyplus.knowledge.models import ActivityObservationState,Activity
from journeyplus.models import AgentInteraction
from journeyplus.product.knowledge_api import BrowseRoutesRequest


def seed(service,factory):
    with factory.begin() as s:
        for _ in range(12):edge(s,public=True)
    initial=service.create();wid=UUID(initial['id'])
    with factory() as s:state=deepcopy(s.get(AgentInteraction,wid).state)
    packet=service._tool('query_membership_routes',{'query':{'use_saved_holdings':False}},state,'浏览公开申请')
    refs=ReferenceMap(state);refs.encode(packet)
    subjects=refs.encode(list(state['routes'])[:2])
    message=service._assemble({'text':'两条公开申请','blocks':[{'type':'route_graph','subject_refs':subjects,'fact_refs':[]}],'next_steps':[]},state,refs)
    message['id']='original'
    with factory.begin() as s:
        s.get(AgentInteraction,wid).state=state
        s.add(WorkspaceMessage(workspace_id=wid,turn_id=uuid4(),ordinal=1,role='ASSISTANT',content=message))
    return wid,subjects


def test_browse_paginates_without_messages_models_or_candidate_loss(factory):
    service=WorkspaceService(factory,None);wid,subjects=seed(service,factory)
    request=BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',expected_revision=0)
    first=browse_routes(service,wid,request)
    assert browse_routes(service,wid,request)==first
    page=first['explorations'][0]
    assert len(page['blocks'][0]['payload']['routes'])==8 and page['browse_cursor']
    assert len(first['messages'])==1 and not page['next_steps']
    focused=service.focus(wid,page['blocks'][0]['subject_refs'][0],page['id'],first['revision'])
    second=browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',cursor=page['browse_cursor'],expected_revision=focused['revision']))
    selected=[r['ref'] for p in second['explorations'] for r in p['blocks'][0]['payload']['routes']]
    assert len(selected)==len(set(selected))==12
    assert second['explorations'][-1]['browse_cursor'] is None
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(WorkspaceTurn))==0
        assert len(s.get(AgentInteraction,wid).state['routes'])==12


def test_browse_rejects_wrong_presentation_and_changed_knowledge(factory):
    service=WorkspaceService(factory,None);wid,subjects=seed(service,factory)
    with pytest.raises(WorkspaceError,match='不属于'):
        browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='other',expected_revision=0))
    with factory.begin() as s:
        activity=s.scalar(select(Activity));s.add(ActivityObservationState(activity_id=activity.id,freshness='STALE'))
    with pytest.raises(WorkspaceError,match='已变化'):
        browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',expected_revision=0))


def test_browsed_objects_join_reference_context_without_fake_conversation(factory):
    service=WorkspaceService(factory,None);wid,subjects=seed(service,factory)
    view=browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',expected_revision=0))
    with factory() as s:state=s.get(AgentInteraction,wid).state
    context=service._presentation_context(view['messages'],state)
    assert context[-1]['id']==view['explorations'][-1]['id']
    assert len(context[-1]['objects'])==8 and len(view['messages'])==1


def test_explicit_explorer_query_uses_filters_without_model_or_holding_writes(factory):
    from journeyplus.agent.route_browsing import explore_routes
    from journeyplus.product.knowledge_api import ExploreRoutesRequest
    from journeyplus.knowledge.routes import RouteQuery
    from journeyplus.models import StatusHolding
    from journeyplus.knowledge.models import MembershipProgram,MembershipTier
    with factory.begin() as s:
        _,target=edge(s,public=True)
        program=s.get(MembershipProgram,s.get(MembershipTier,target).program_id);program.category='AIRLINE';program.alliance='TEST_ALLIANCE'
    service=WorkspaceService(factory,None);initial=service.create();wid=UUID(initial['id'])
    view=explore_routes(service,wid,ExploreRoutesRequest(query=RouteQuery(use_saved_holdings=False,category='AIRLINE',alliance='TEST_ALLIANCE'),expected_revision=0))
    page=view['explorations'][-1];route=page['blocks'][0]['payload']['routes'][0]
    assert route['from'] is None and page['query_summary']['alliance']=='TEST_ALLIANCE'
    assert not view['messages']
    with factory() as s:assert s.scalar(select(func.count()).select_from(StatusHolding))==0
    empty=explore_routes(service,wid,ExploreRoutesRequest(query=RouteQuery(use_saved_holdings=False,category='HOTEL'),expected_revision=view['revision']))
    assert empty['explorations'][-1]['blocks']==[] and '尚未找到' in empty['explorations'][-1]['text']


def test_page_numbers_follow_full_query_order(factory):
    service=WorkspaceService(factory,None);wid,subjects=seed(service,factory)
    view=browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',expected_revision=0))
    first=view['explorations'][-1]
    second=browse_routes(service,wid,BrowseRoutesRequest(anchor_ref=subjects[0],presentation_id='original',cursor=first['browse_cursor'],expected_revision=view['revision']))
    assert [r['presentation_index'] for r in second['explorations'][-1]['blocks'][0]['payload']['routes']]==[9,10,11,12]
