from uuid import UUID
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from journeyplus.models import Base,AgentInteraction
from journeyplus.knowledge.publication import CatalogService
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
from journeyplus.agent.workspace_contracts import MessageRequest,TaskUpdate
from journeyplus.agent.turn_planning import RouteTurnPlan,apply_plan
from journeyplus.agent.task_context import apply_task_update


@pytest.fixture
def factory():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine,expire_on_commit=False)
    engine.dispose()


def test_plan_replaces_source_before_execution_and_keeps_destination(factory):
    with factory.begin() as s:
        c=CatalogService(s);old=c.program('Previous Club');old_tier=c.tier(old.id,'Gold')
        new=c.program('New Club');new_tier=c.tier(new.id,'Gold');target=c.program('Destination')
        old_id,new_id,target_id=map(str,(old_tier.id,new_tier.id,target.id))
    class Provider:
        metadata=SequenceAIProvider([]).metadata
        calls=0
        def generate_structured(self,**kwargs):
            self.calls+=1;p=json.loads(kwargs['user_prompt'])
            if self.calls==1:
                assert kwargs['output_model'] is RouteTurnPlan
                assert p['latest_user_input']=='New Club Gold 呢'
                result={'kind':'ROUTES','source_action':'REPLACE','sources':[{'text':'New Club','alternate_names':['New Club'],'tier':'Gold'}],'target_action':'KEEP','request':'New Club Gold 到 Destination'}
            elif self.calls==2:
                assert p['query']['starting_tier_ids']==[]
                tier=p['catalog'][0]['data']['catalog']['programs'][0]['tiers'][0]['id']
                result={'starting_tier_refs':[tier],'target_program_ref':'UNDISCLOSED_UNUSED'}
            else:result={'action':'ANSWER','payload':{'text':'本次查询暂未找到已核实路径。'}}
            return kwargs['output_model'].model_validate(result)
    provider=Provider();service=WorkspaceService(factory,provider,plan_route_turns=True);view=service.create()
    with factory.begin() as s:
        row=s.get(AgentInteraction,UUID(view['id']));row.state={**row.state,'query':{'starting_tier_ids':[old_id],'target_program_id':target_id,'use_saved_holdings':False},'task_context':{'intent':'ROUTES','target_scope':'SELECTED'}}
    answer=service.message(UUID(view['id']),MessageRequest(text='New Club Gold 呢',client_message_id='switch',expected_revision=view['revision']))['messages'][-1]
    with factory() as s:
        state=s.get(AgentInteraction,UUID(view['id'])).state
        assert state['query']['starting_tier_ids']==[new_id]
        assert state['query']['target_program_id']==target_id
        assert state['task_context']['target_scope']=='SELECTED'
    assert provider.calls==3
    assert answer['input_observations'][0]['action']=='PLAN'
    assert any(b['tool']=='query_membership_routes' and b['status']!='FAILED' for b in answer['basis'])


def test_plan_cannot_be_overwritten_by_later_default_task_update():
    state={'turn_route_plan':{'source_action':'REPLACE'},'task_context':{'intent':'ROUTES','source_text':'New Gold','target_scope':'ANY'}}
    apply_task_update(state,TaskUpdate(intent='ROUTES',source_text='Old Gold',target_scope='SELECTED'),'New Gold所有路径')
    assert state['task_context']['source_text']=='New Gold'
    assert state['task_context']['target_scope']=='ANY'


def test_plan_missing_source_still_reads_and_keeps_target(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Destination');c.tier(p.id,'Gold')
    service=WorkspaceService(factory,None);state={};packets=[];basis=[]
    plan=RouteTurnPlan(kind='ROUTES',source_action='REPLACE',sources=[{'text':'Gold','alternate_names':['Gold']}],target_action='SELECT',target={'text':'Destination','alternate_names':['Destination']},request='Gold 到 Destination')
    answer=apply_plan(service,plan,state,packets,basis,lambda *args:None)
    assert answer and state['unresolved_question']['field']=='SOURCE_PROGRAM'
    assert state['task_context']['target_scope']=='SELECTED'
    assert len(basis)==2 and state['planned_target_programs']


def test_replaced_source_must_belong_to_planned_catalogue(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Old Club');t=c.tier(p.id,'Gold');old_id=str(t.id)
    service=WorkspaceService(factory,None)
    state={'turn_route_plan':{'source_action':'REPLACE','target_action':'ANY'},'planned_source_programs':[]}
    with pytest.raises(WorkspaceError,match='起点不属于本轮查询计划'):
        service._tool('query_membership_routes',{'query':{'starting_tier_ids':[old_id]}},state,'New Club Gold 呢')
    assert not state.get('route_searches')


def test_registered_tier_aliases_constrain_selection_without_brand_rules(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Example Rewards');basic=c.tier(p.id,'Basic');premium=c.tier(p.id,'Premium')
        c.alias('Gold',p.id,premium.id);wrong=str(basic.id);right=str(premium.id)
    service=WorkspaceService(factory,None);state={'routes':{},'steps':{}};packets=[];basis=[]
    plan=RouteTurnPlan(kind='ROUTES',source_action='REPLACE',sources=[{'text':'Example Rewards','alternate_names':['Example Rewards'],'tier':'Gold'}],target_action='ANY',request='Example Gold 所有路径')
    assert apply_plan(service,plan,state,packets,basis,lambda *args:None) is None
    assert state['planned_source_tier_groups']==[[right]]
    assert any(t.get('aliases') for t in packets[0]['data']['catalog']['programs'][0]['tiers'])
    with pytest.raises(WorkspaceError,match='明确等级名称或已登记别名不符'):
        service._tool('query_membership_routes',{'query':{'starting_tier_ids':[wrong],'use_saved_holdings':False}},state,'Example Gold')
    assert not state.get('route_searches')


def test_inherited_unresolved_target_is_located_during_source_reply(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Source');c.tier(p.id,'Gold');c.program('Destination')
    service=WorkspaceService(factory,None)
    state={'query':{'starting_tier_ids':[]},'task_context':{'intent':'ROUTES','target_scope':'SELECTED','target_text':'Destination'}}
    plan=RouteTurnPlan(kind='ROUTES',source_action='REPLACE',sources=[{'text':'Source','alternate_names':['Source'],'tier':'Gold'}],target_action='KEEP',request='Source Gold 到 Destination')
    packets=[];basis=[];apply_plan(service,plan,state,packets,basis,lambda *args:None)
    assert [b['role'] for b in basis]==['source','target']
    assert state['turn_route_plan']['target_action']=='SELECT'
    assert state['planned_target_programs']


def test_normalized_lookup_finds_catalogue_when_original_language_is_absent(factory):
    from pydantic import ValidationError
    from journeyplus.agent.turn_planning import IdentityLookup
    with pytest.raises(ValidationError):
        IdentityLookup(text='示例会籍',alternate_names=[])
    assert IdentityLookup(text='示例会籍',alternate_names=['Example','Example','Example Rewards','ER','Extra']).alternate_names==['Example','Example Rewards','ER']
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Example Rewards');t=c.tier(p.id,'Gold');tier_id=str(t.id)
    service=WorkspaceService(factory,None);state={};packets=[];basis=[]
    plan=RouteTurnPlan(kind='ROUTES',source_action='REPLACE',sources=[{'text':'示例会籍','alternate_names':['Example Rewards'],'tier':'Gold'}],target_action='ANY',request='示例金卡所有路径')
    apply_plan(service,plan,state,packets,basis,lambda *args:None)
    assert state['planned_source_tier_groups']==[[tier_id]]
    assert len(basis)==1


def test_compound_lookup_requires_real_rank_in_programme(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Example Rewards');c.tier(p.id,'Gold')
    service=WorkspaceService(factory,None)
    def lookup(term):
        return service._tool('query_activity_materials',{'view':'CATALOG','selector':{'text':term}}, {},term)
    assert lookup('Example Gold')['data']['catalog']['programs']
    assert not lookup('Example Imaginary')['data']['catalog']['programs']
    assert not lookup('Gold')['data']['catalog']['programs']


def test_pending_identities_keep_normalized_terms_across_clarification(factory):
    with factory.begin() as s:
        c=CatalogService(s);p=c.program('Source Club');c.tier(p.id,'Gold');c.program('Destination Club')
    service=WorkspaceService(factory,None)
    state={'query':{},'source_identity_pending':True,'task_context':{
        'intent':'ROUTES','target_scope':'SELECTED','target_text':'目标中文名',
        'target_lookup':{'text':'目标中文名','alternate_names':['Destination Club']},
        'source_lookups':[{'text':'起点中文名','alternate_names':['Source Club'],'tier':'Gold'}]}}
    plan=RouteTurnPlan(kind='ROUTES',source_action='KEEP',target_action='KEEP',request='继续当前查询')
    packets=[];basis=[];apply_plan(service,plan,state,packets,basis,lambda *args:None)
    assert [p['status'] for p in packets]==['CATALOG_ONLY','CATALOG_ONLY']
    assert state['planned_source_programs'] and state['planned_target_programs']
