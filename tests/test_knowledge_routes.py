"""Graph-level acceptance cases: public roots, history and coverage budgets."""
from copy import deepcopy
from uuid import UUID

from tests.test_knowledge import knowledge_session, fixture_draft
from journeyplus.knowledge.contracts import KnowledgeDraft
from journeyplus.knowledge.models import MembershipTier
from journeyplus.knowledge.publication import PublicationService
from journeyplus.knowledge.routes import RouteQuery, RouteService


def edge(session, source_tier=None, *, public=False, alternative=False, condition=None, unknown_price=False,target_tier=None,transform=None):
    draft,_,_=fixture_draft(session)
    data=draft.model_dump(mode='json');option=data['options'][0]
    option['mappings']=[option['mappings'][1]]
    option['prices']=[option['prices'][1]]
    if target_tier:
        tier=session.get(MembershipTier,target_tier)
        option['mappings'][0]['target_tier_id']=str(tier.id)
        option['mappings'][0]['target_program_id']=str(tier.program_id)
        option['prices'][0]['target_tier_id']=str(tier.id)
    if unknown_price:option['prices'][0]['availability']='UNKNOWN'
    scope=option['source_scope']
    if public:
        scope={'kind':'PUBLIC','evidence_ids':scope['evidence_ids']}
        option['method']='CHALLENGE'
        option['challenge']={'known_state':'KNOWN','value':{'kind':'REQUIRED'},'evidence_ids':scope['evidence_ids']}
    elif source_tier:
        tier=session.get(MembershipTier,source_tier)
        scope={**scope,'program_id':str(tier.program_id),'tier_ids':[str(tier.id)]}
    option['source_scope']=scope;option['mappings'][0]['source_scope']=scope
    if condition:
        option['conditions']={'items':[{'condition_id':'eligibility','known_state':'KNOWN',
                                     'evidence_ids':scope['evidence_ids'],**condition}]}
    if alternative:
        second=deepcopy(option);second['logical_key']='alternative-method'
        second['label']='Alternative application method';data['options'].append(second)
    root=UUID(scope['tier_ids'][0]) if scope.get('tier_ids') else None
    if transform:transform(option)
    PublicationService(session).publish(KnowledgeDraft.model_validate(data))
    return root,UUID(option['mappings'][0]['target_tier_id'])


def test_public_challenge_has_no_fake_starting_membership(knowledge_session):
    s=knowledge_session;_,target=edge(s,public=True)
    result=RouteService(s).query(RouteQuery(target_tier_id=target))
    assert len(result['data']['cards'])==1
    card=result['data']['cards'][0]
    assert card['from'] is None and card['challenge']=='REQUIRED'
    assert result['data']['steps'][card['step_refs'][0]]['from_tier_id'] is None


def test_query_budget_and_freshness_changes_preserve_distinct_route_snapshots(knowledge_session):
    from sqlalchemy import select
    from journeyplus.knowledge.models import ActivityObservationState,Activity
    s=knowledge_session;root,target=edge(s)
    service=RouteService(s)
    first=service.query(RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=200,currency='USD'))
    second=service.query(RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=100,currency='USD'))
    assert first['data']['cards'][0]['ref']!=second['data']['cards'][0]['ref']
    activity=s.scalars(select(Activity)).first()
    observation=s.get(ActivityObservationState,activity.id)
    if observation is None:
        observation=ActivityObservationState(activity_id=activity.id,freshness='STALE');s.add(observation)
    else:observation.freshness='STALE'
    s.flush()
    refreshed=service.query(RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=200,currency='USD'))
    assert first['data']['cards'][0]['ref']!=refreshed['data']['cards'][0]['ref']
    assert first['data']['cards'][0]['step_refs']!=refreshed['data']['cards'][0]['step_refs']


def test_eight_steps_are_searchable_and_budget_reports_partial(knowledge_session):
    s=knowledge_session;root,target=edge(s)
    for _ in range(7):_,target=edge(s,target)
    query=RouteQuery(starting_tier_ids=[root],target_tier_id=target)
    complete=RouteService(s).query(query)
    assert complete['coverage']['search_complete']
    assert complete['data']['cards'][0]['step_count']==8
    partial=RouteService(s).query(query,max_states=1)
    assert not partial['coverage']['search_complete']
    assert partial['coverage']['stopped_reason']=='STATE_BUDGET'


def test_alternative_arrivals_keep_shared_successor_paths(knowledge_session):
    s=knowledge_session;root,middle=edge(s,alternative=True);_,target=edge(s,middle)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    cards=result['data']['cards']
    assert len(cards)==2
    assert cards[0]['step_refs'][0]!=cards[1]['step_refs'][0]
    assert cards[0]['step_refs'][1]==cards[1]['step_refs'][1]
    assert result['coverage']['search_complete']


def test_cycle_is_pruned_without_losing_forward_path(knowledge_session):
    s=knowledge_session;root,middle=edge(s)
    edge(s,middle,target_tier=root)
    _,target=edge(s,middle)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    assert result['coverage']['search_complete']
    assert len(result['data']['cards'])==1 and result['data']['cards'][0]['step_count']==2


def test_unrelated_mappings_do_not_consume_candidate_edge_budget(knowledge_session):
    s=knowledge_session;root,target=edge(s)
    for _ in range(5):edge(s)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target),max_edges=2)
    assert result['coverage']['search_complete']
    assert result['coverage']['checked_edges']==1
    assert len(result['server_routes'])==1


def test_matched_intermediate_does_not_inherit_earned_origin(knowledge_session):
    s=knowledge_session;root,middle=edge(s)
    _,target=edge(s,middle,condition={'topic':'SOURCE_ACQUISITION','operator':'EQ',
                                    'value':'EARNED','raw_text':'Earned status only'})
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target,source_acquisition='EARNED'))
    assert result['data']['cards']==[] and result['coverage']['search_complete']
    assert result['data']['reason_counts']['来源或资格不适用']>0


def test_remaining_validity_uses_saved_holding_expiry(knowledge_session):
    from datetime import date,timedelta
    from journeyplus.models import StatusHolding
    s=knowledge_session;root,target=edge(s,condition={'topic':'MIN_REMAINING_VALIDITY','operator':'GTE',
                                                     'value':90,'raw_text':'At least 90 days remaining'})
    tier=s.get(MembershipTier,root)
    holding=StatusHolding(program_key=str(root),tier_key='gold',program_display_name='Fixture',tier_display_name='Gold',
                          program_id=tier.program_id,tier_id=root,valid_until=date.today()+timedelta(days=30))
    s.add(holding);s.flush()
    query=RouteQuery(target_tier_id=target)
    assert RouteService(s).query(query)['data']['cards']==[]
    holding.valid_until=date.today()+timedelta(days=120);s.flush()
    result=RouteService(s).query(query)
    card=result['data']['cards'][0];step=result['data']['steps'][card['step_refs'][0]]
    assert step['constraint_checks'][0]['result']=='PASS'
    assert step['constraint_checks'][0]['actual']==120


def test_unverified_price_remains_visible_but_is_not_confirmed_total(knowledge_session):
    s=knowledge_session;root,target=edge(s,unknown_price=True)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target,max_amount=200,currency='EUR'))
    card=result['data']['cards'][0]
    assert card['classification']=='UNKNOWN' and card['needs_inspection']
    assert card['cost']['totals']==[] and not card['cost']['is_proven_free']
    item=card['cost']['conditional_items'][0]
    assert float(item['amount'])==200 and item['applicability']=='UNKNOWN'


def test_published_unknown_source_still_means_incomplete_search(knowledge_session):
    from journeyplus.knowledge.models import OptionMapping
    from sqlalchemy import select
    s=knowledge_session
    def unknown(option):
        option['source_scope']=option['mappings'][0]['source_scope']={'kind':'UNKNOWN','evidence_ids':[]}
    root,target=edge(s,transform=unknown)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    assert result['coverage']['pending_activity_count']==0
    assert result['coverage']['incomplete_published_activity_count']==1
    assert result['coverage']['search_complete'] is False
    assert result['coverage']['stopped_reason']=='KNOWLEDGE_GAPS'
    assert not result['data']['cards']


def test_conflicting_same_charge_keeps_both_quotes_without_adding(knowledge_session):
    from sqlalchemy import select
    from decimal import Decimal
    from journeyplus.knowledge.models import OptionPrice
    s=knowledge_session;root,target=edge(s)
    if s.bind.dialect.name=='postgresql':
        import pytest
        pytest.skip('Deliberately corrupt read-side fixture; PostgreSQL correctly forbids altering published children')
    first=s.scalar(select(OptionPrice))
    # Simulate two independently sourced rows in the read-side robustness test.
    values={column.name:getattr(first,column.name) for column in OptionPrice.__table__.columns if column.name not in {'id','created_at','updated_at'}}
    values.update(price_key='second-source',amount=Decimal('250'),mapping_scope='ALL_MAPPINGS',raw_text='Conflicting second source')
    second=OptionPrice(**values);s.add(second);s.flush()
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    route=result['data']['cards'][0]
    assert route['cost']['state']=='CONFLICT' and route['cost']['totals']==[]
    competing=route['cost']['conditional_items']
    assert {Decimal(p['amount']) for p in competing}=={Decimal('200'),Decimal('250')}
    assert all(p['applicability']=='CONFLICT' for p in competing)
    assert not route['cost']['is_proven_free']


def test_future_application_start_is_not_available_today(knowledge_session):
    from datetime import date,timedelta
    from sqlalchemy import select
    from journeyplus.knowledge.models import ApplicationOptionVersion
    s=knowledge_session
    def future(option):
        option['application_window']={'start':{'known_state':'KNOWN','value':{'precision':'DATE','timezone':'UTC','date':(date.today()+timedelta(days=2)).isoformat()},'evidence_ids':option['source_scope']['evidence_ids']}}
    root,target=edge(s,transform=future)
    result=RouteService(s).query(RouteQuery(starting_tier_ids=[root],target_tier_id=target))
    assert not result['data']['cards'] and result['data']['reason_counts']['尚未开放申请']>0


def test_evaluation_context_changes_at_intraday_deadline(knowledge_session):
    from datetime import datetime,UTC
    from sqlalchemy import select
    from journeyplus.knowledge.models import ApplicationOptionVersion
    s=knowledge_session
    def deadline(option):
        option['application_window']={'end':{'known_state':'KNOWN','value':{
            'precision':'INSTANT','instant':'2026-09-06T08:00:00Z'},'evidence_ids':option['source_scope']['evidence_ids']}}
    edge(s,transform=deadline)
    service=RouteService(s)
    assert service.evaluation_context(datetime(2026,9,6,7,59,tzinfo=UTC)) != service.evaluation_context(datetime(2026,9,6,8,1,tzinfo=UTC))


def test_explicit_start_does_not_silently_union_unrelated_saved_holdings(knowledge_session):
    from journeyplus.models import StatusHolding
    s=knowledge_session;saved,_=edge(s);explicit,_=edge(s)
    s.add(StatusHolding(program_key=str(saved),tier_key='gold',program_display_name='Saved',tier_display_name='Gold',program_id=s.get(MembershipTier,saved).program_id,tier_id=saved))
    s.flush()
    def roots(query):
        result=RouteService(s).query(query)
        return {result['server_steps'][r['step_refs'][0]]['from_tier_id'] for r in result['server_routes'].values()}
    assert roots(RouteQuery(starting_tier_ids=[explicit]))=={str(explicit)}
    assert roots(RouteQuery(starting_tier_ids=[explicit],use_saved_holdings=True))=={str(explicit),str(saved)}
    assert roots(RouteQuery(use_saved_holdings=False))==set()
    assert roots(RouteQuery())=={str(saved)}
