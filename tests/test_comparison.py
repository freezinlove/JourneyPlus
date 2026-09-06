from decimal import Decimal
import pytest
from pydantic import ValidationError
from journeyplus.agent.comparison import comparison_rows
from journeyplus.agent.workspace_contracts import ContentSelection


def test_comparison_preserves_intermediate_step_unknowns_and_separate_currencies():
    costs={'state':'PARTIAL','totals':[{'currency':'USD','amount':'149'},{'currency':'EUR','amount':'89'}],'is_proven_free':False}
    routes=[{'from':'A','to':'C','step_refs':['ab','bc'],'cost':costs,'challenge':'UNKNOWN','eligibility':'UNKNOWN'}]
    steps={'ab':{'to':'B','status_validity':{'known_state':'UNKNOWN'}},'bc':{'to':'C','status_validity':{'known_state':'KNOWN','value':{'kind':'DURATION','months':12,'anchor':'APPROVAL'}}}}
    rows=comparison_rows(routes,steps,['cost','steps','validity','challenge','cost'])
    assert len(rows)==4
    assert rows[0]['cells']==[costs]
    assert rows[1]['cells']==[['A','B','C']]
    assert rows[2]['cells'][0][0]['value']['known_state']=='UNKNOWN'
    assert rows[2]['cells'][0][1]['value']['value']['months']==12
    assert rows[3]['cells']==['UNKNOWN']


def test_unknown_model_comparison_dimension_cannot_become_a_formal_claim():
    with pytest.raises(ValidationError):ContentSelection(type='route_comparison',columns=['success_probability'])
    with pytest.raises(ValueError):comparison_rows([],{},['success_probability'])


def test_explicit_validity_dimension_survives_budget_fallback():
    from journeyplus.agent.comparison import requested_columns
    assert requested_columns('整理费用、步骤、有效期比较表',[])==['cost','steps','validity']
    assert 'validity' in requested_columns('补充有效期',['cost'])


def test_comparison_display_respects_explicit_graph_request():
    from journeyplus.agent.comparison import comparison_requested
    assert comparison_requested('比较两条路径的费用和有效期')
    assert not comparison_requested('用图比较两条路径')
    assert not comparison_requested('用推荐图展示，优先步骤少，再比较已知费用')


def test_explicit_pair_cannot_be_lost_when_model_selects_only_one():
    from journeyplus.agent.comparison import resolve_comparison_scope
    from journeyplus.knowledge.references import ReferenceMap
    refs=ReferenceMap({'references':{'K1':'route-a','K2':'route-b'}})
    presentations=[{'objects':[{'type':'route','ref':'K1'},{'type':'route','ref':'K2'}]}, {'objects':[{'type':'activity','ref':'K3'}]}]
    assert resolve_comparison_scope('比较这两条路径的有效期',[],presentations,refs,{'route-a':{},'route-b':{}})==['route-a','route-b']
    assert resolve_comparison_scope('换个话题，酒店有啥新闻',[],presentations,refs,{'route-a':{},'route-b':{}})==[]


def test_new_explicit_target_does_not_inherit_old_comparison_scope():
    from journeyplus.agent.comparison import resolve_comparison_scope
    from journeyplus.knowledge.references import ReferenceMap
    refs=ReferenceMap({'references':{'K1':'a','K2':'b'}})
    assert resolve_comparison_scope('比较这两条路径，但目标改为另一个项目',['K1','K2'],[],refs,{'a':{},'b':{}})==[]


def test_same_turn_two_target_queries_preserve_both_in_fallback():
    from journeyplus.agent.comparison import current_target_comparison
    from journeyplus.knowledge.references import ReferenceMap
    state={'current_question':'比较A和B的费用','routes':{r:{'ref':r,'classification':'MATCH'} for r in ['a','b','b2']},
           'current_target_searches':[{'target':['A',None],'route_refs':['a']},{'target':['B',None],'route_refs':['b','b2']}]}
    refs=ReferenceMap({'references':{'K1':'a','K2':'b','K3':'b2'}})
    assert current_target_comparison(state,refs)==['a','b']
    state['current_question']='只用图展示B'
    assert current_target_comparison(state,refs)==[]
