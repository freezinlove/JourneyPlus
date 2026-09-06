from sqlalchemy import select
from uuid import UUID
from journeyplus.agent.workspace import WorkspaceWaitService,holding_snapshot
from journeyplus.knowledge.routes import RouteQuery
from journeyplus.knowledge.models import Activity,ActivityObservationState
from journeyplus.models import AgentWaitGoal,now_utc
from tests.test_workspace import factory
from tests.test_knowledge_routes import edge


def test_seen_result_does_not_repeat_after_observation_changes_but_new_path_can_hit(factory):
    with factory.begin() as s:
        _,target=edge(s,public=True)
        goal=AgentWaitGoal(status='ACTIVE',conditions_schema_version=2,query=RouteQuery(target_tier_id=target).model_dump(mode='json'),holding_snapshot=holding_snapshot(s))
        s.add(goal);s.flush();gid=goal.id
    waiting=WorkspaceWaitService(factory)
    first=waiting.check();assert first['status']=='HIT' and first['model_calls']==0
    current=waiting.current();assert current['status']=='RESULT_PENDING'
    assert waiting.current()==current
    assert waiting.check()['status']=='NO_ACTIVE_GOAL'
    waiting.seen(gid,UUID(current['result_id']))
    with factory.begin() as s:
        goal=s.get(AgentWaitGoal,gid)
        assert len(goal.seen_candidate_signatures)==1
        goal.status='ACTIVE';goal.pending_result=None
        activity=s.scalar(select(Activity))
        s.add(ActivityObservationState(activity_id=activity.id,freshness='FRESH',last_checked_at=now_utc()))
    assert waiting.check()['status']=='DUPLICATE'
    with factory.begin() as s:edge(s,public=True,target_tier=target)
    assert waiting.check()['status']=='HIT'
    assert len(waiting.current()['pending_result']['routes'])==1


def test_legacy_wait_reader_never_consumes_v2_query(factory):
    from journeyplus.agent.waiting import WaitGoalService
    with factory.begin() as s:
        s.add(AgentWaitGoal(status='ACTIVE',conditions_schema_version=2,query={}))
    with factory() as s:
        assert WaitGoalService(s).current() is None
        result=WaitGoalService(s).check_current(lambda *args: (_ for _ in ()).throw(AssertionError('legacy model called')))
        assert result.status=='NO_GOAL'


def test_adjustment_must_really_make_supporting_route_match(factory):
    import pytest
    from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
    from journeyplus.ai.provider import SequenceAIProvider
    from journeyplus.knowledge.routes import RouteService
    from journeyplus.knowledge.references import ReferenceMap
    with factory.begin() as s:
        root,target=edge(s)
        query=RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=10,currency='EUR')
        result=RouteService(s).query(query)
    state={'query':query.model_dump(mode='json'),'routes':result['server_routes']}
    refs=ReferenceMap(state);route=next(iter(state['routes']))
    short=refs.encode(route)
    service=WorkspaceService(factory,SequenceAIProvider([]))
    proposal={'kind':'QUERY_ADJUST','changes':{'max_amount':11},'support_refs':[short]}
    with pytest.raises(WorkspaceError,match='未能'):service._validate_proposal(proposal,state)
    proposal['changes']={'max_amount':200}
    service._validate_proposal(proposal,state)
    assert proposal['query_snapshot']==result['snapshot']


def test_old_adjustment_cannot_apply_to_a_changed_query_even_with_current_revision(factory):
    from copy import deepcopy
    from datetime import datetime,UTC,timedelta
    from uuid import UUID
    import pytest
    from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
    from journeyplus.agent.workspace_contracts import ConfirmRequest
    from journeyplus.knowledge.references import ReferenceMap
    from journeyplus.models import AgentInteraction
    service=WorkspaceService(factory,None);view=service.create()
    with factory.begin() as s:root,target=edge(s)
    state={'routes':{},'steps':{},'current_question':'预算最多100欧元，请给最小调整'}
    result=service._tool('query_membership_routes',{'query':{'starting_tier_ids':[str(root)],'target_tier_id':str(target),'max_amount':100,'currency':'EUR'}},state,state['current_question'])
    refs=ReferenceMap(state);ref=refs.encode(next(iter(state['routes'])))
    service._stage_proposal({'kind':'QUERY_ADJUST','changes':{'max_amount':200},'support_refs':[ref],'reason':'调整预算'},state,refs,0,datetime.now(UTC)+timedelta(hours=1))
    state['query']['max_amount']='150'
    with factory.begin() as s:
        row=s.get(AgentInteraction,UUID(view['id']));row.state={**deepcopy(row.state),**state}
    with pytest.raises(WorkspaceError,match='查询条件已变化'):
        service.confirm(UUID(view['id']),ConfirmRequest(pending_action_id=state['pending_action']['id'],expected_revision=0,client_action_id='changed-query',decision='CONFIRM'))
    with factory() as s:assert s.get(AgentInteraction,UUID(view['id'])).state['query']['max_amount']=='150'


def test_adopting_result_is_not_delivery_and_supports_details_after_reload(factory):
    from journeyplus.agent.workspace import WorkspaceService
    with factory.begin() as s:
        _,target=edge(s,public=True)
        goal=AgentWaitGoal(status='ACTIVE',conditions_schema_version=2,query=RouteQuery(target_tier_id=target).model_dump(mode='json'),holding_snapshot=holding_snapshot(s))
        s.add(goal);s.flush();gid=goal.id
    waiting=WorkspaceWaitService(factory);waiting.check();result=waiting.current()
    service=WorkspaceService(factory,None);view=service.create();wid=UUID(view['id']);rid=UUID(result['result_id'])
    adopted=service.adopt_wait_result(wid,gid,rid,view['revision'])
    assert waiting.current()['status']=='RESULT_PENDING'
    assert service.adopt_wait_result(wid,gid,rid,view['revision'])==adopted
    assert WorkspaceService(factory,None).read(wid)==adopted
    assert len(adopted['messages'])==1 and adopted['messages'][0]['model_calls']==0
    waiting.seen(gid,rid);assert waiting.current()['status']=='COMPLETED'
    assert service.read(wid)==adopted
    message=adopted['messages'][0];step_ref=next(iter(message['blocks'][0]['payload']['steps']))
    focused=service.focus(wid,step_ref,message['id'],adopted['revision'])
    assert focused['focus']['ref']==step_ref and focused['messages']==adopted['messages']


def test_wait_proposal_discloses_partial_coverage_and_every_active_constraint(factory):
    from journeyplus.agent.workspace import WorkspaceService
    from journeyplus.ai.provider import SequenceAIProvider
    with factory.begin() as s:root,target=edge(s)
    query=RouteQuery(starting_tier_ids=[root],target_tier_id=target,free_only=True,require_proven_eligibility=True,prior_participation='NEVER',preferences=['FEWER_STEPS'])
    proposal={'kind':'WAIT_CREATE','changes':{'query':query.model_dump(mode='json')},'reason':'全库没有方案'}
    WorkspaceService(factory,SequenceAIProvider([]))._validate_proposal(proposal,{})
    assert proposal['reason']!='全库没有方案'
    labels={row['label'] for row in proposal['display']}
    assert {'起点会籍','仅接受资格已证实','历史参与情况','排序偏好'}<=labels
    assert proposal['changes']['query']['require_proven_eligibility'] is True


def test_budget_adjustment_cannot_exceed_minimum_needed_by_support(factory):
    import pytest
    from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
    from journeyplus.knowledge.routes import RouteService
    from journeyplus.knowledge.references import ReferenceMap
    with factory.begin() as s:
        root,target=edge(s)
        query=RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=100,currency='EUR')
        found=RouteService(s).query(query)
    state={'query':query.model_dump(mode='json'),'routes':found['server_routes']}
    refs=ReferenceMap(state);short=refs.encode(next(iter(state['routes'])))
    proposal={'kind':'QUERY_ADJUST','changes':{'max_amount':250},'support_refs':[short]}
    with pytest.raises(WorkspaceError,match='最小调整'):WorkspaceService(factory,None)._validate_proposal(proposal,state)
