from uuid import uuid4

import pytest

from journeyplus.agent.answer_grounding import route_text_issues,verified_route_text
from journeyplus.agent.workspace import WorkspaceService,WorkspaceError
from journeyplus.knowledge.references import ReferenceMap


def route():
    return {'ref':str(uuid4()),'from':'Aeroplan 50K','to':'Gold Sparrow','step_refs':[],
            'challenge':'UNKNOWN','eligibility':'UNKNOWN',
            'material_caveats':['Government issued identity document or Canadian passport required. Residence Permits are not accepted.'],
            'cost':{'state':'KNOWN','is_proven_free':False,'totals':[{'currency':'USD','amount':'149'}]}}


def test_unknown_challenge_partial_search_and_document_country_are_not_claimed_known():
    r=route()
    issues=route_text_issues('无挑战要求，当前路径仅此一条，请补充居住国。',[r],search_complete=False)
    assert set(issues)=={'UNKNOWN_CHALLENGE_ASSERTED_NONE','PARTIAL_SEARCH_ASSERTED_UNIQUE','DOCUMENT_COUNTRY_IS_NOT_RESIDENCY'}
    safe=verified_route_text([r],search_complete=False)
    assert 'USD 149' in safe and '尚未核实' in safe and '覆盖不完整' in safe
    assert not route_text_issues(safe,[r],search_complete=False)
    assert not route_text_issues('不能认定无挑战，也不能认定唯一的路径。',[r],search_complete=False)
    assert 'UNKNOWN_CHALLENGE_ASSERTED_NONE' in route_text_issues('无需挑战（挑战状态未知）。',[r],search_complete=True)


def test_real_residency_condition_is_allowed():
    r=route();r['material_caveats'].append('Applicants must be residents of Canada.')
    assert not route_text_issues('请核对居住国。',[r],search_complete=True)


def test_assembly_replaces_contradiction_without_model_and_rejects_hidden_references():
    r=route();state={'routes':{r['ref']:r},'steps':{}}
    refs=ReferenceMap(state);short=refs.encode(r['ref'])
    service=WorkspaceService(None,None)
    payload={'text':'当前路径仅此一条，无挑战要求。','blocks':[{'type':'route_graph','subject_refs':[short],'fact_refs':[]}],
             'claim_refs':[short],'next_steps':[{'message':'补充居住国','subject_refs':[short]}]}
    result=service._assemble(payload,state,refs)
    assert result['grounding_issues'] and result['blocks']
    assert all('居住国' not in step['message'] for step in result['next_steps'])
    assert 'USD 149' in result['text']
    payload['claim_refs']=['K9999']
    with pytest.raises(WorkspaceError,match='未披露'):service._assemble(payload,state,refs)


def test_route_block_rejects_fact_from_different_step():
    r=route();state={'routes':{r['ref']:r},'steps':{}};refs=ReferenceMap(state)
    payload={'text':'路线','blocks':[{'type':'route_graph','subject_refs':[refs.encode(r['ref'])],
                                    'fact_refs':[refs.encode(str(uuid4())+'/prices/0')]}],'next_steps':[]}
    with pytest.raises(WorkspaceError,match='步骤不一致'):WorkspaceService.__new__(WorkspaceService)._assemble(payload,state,refs)


def test_route_formal_text_is_not_dependent_on_keyword_guard():
    r=route();state={'routes':{r['ref']:r},'steps':{}};refs=ReferenceMap(state)
    payload={'text':'该活动不涉及挑战，无其他隐藏费用，收费USD99。',
             'blocks':[{'type':'route_graph','subject_refs':[refs.encode(r['ref'])],'fact_refs':[]}],
             'next_steps':[{'label':'只花99','message':'按99美元办理','subject_refs':[refs.encode(r['ref'])]}]}
    result=WorkspaceService(None,None)._assemble(payload,state,refs)
    assert result['presentation_policy']=='SERVER_ROUTE_FACTS'
    assert 'USD 149' in result['text'] and '挑战要求尚未核实' in result['text']
    assert '99' not in str(result) and '隐藏费用' not in str(result)


def test_formal_route_text_preserves_paid_intermediate_membership():
    r=route();r.update(to='Club Avolta Gold',step_refs=['first','second'])
    steps={'first':{'from':'Aeroplan 50K','to':'Gold Sparrow'},
           'second':{'from':'Gold Sparrow','to':'Club Avolta Gold'}}
    text=verified_route_text([r],search_complete=False,steps=steps)
    assert 'Aeroplan 50K → Gold Sparrow → Club Avolta Gold' in text
    assert 'USD 149' in text


def test_activity_currency_comparison_preserves_scope_without_subtraction():
    from journeyplus.agent.answer_grounding import verified_activity_prices
    material={'data':{'catalog':[{'tier_ref':'gold','tier_name':'Gold'}], 'facts':[
        {'field':'prices','label':region,'value':[{'ref':region,'target_tier_id':'gold',
            'known_state':'KNOWN','amount':amount,'currency':currency,'availability':'AVAILABLE',
            'fee_role':'APPLICATION','raw_text':region+' residents only','conditions':{'items':[]}}]}
        for region,amount,currency in [('Greece','199','EUR'),('Brazil','299','USD')]]}}
    text=verified_activity_prices([material,material])
    assert text.count('EUR 199')==1 and 'USD 299' in text
    assert '不能直接相减' in text and 'Greece residents only' in text


def test_specific_target_fee_and_unmapped_upgrade_caveat_are_not_lost():
    from journeyplus.agent.answer_grounding import verified_activity_prices
    prices=[{'ref':name,'target_scope':'EXACT','target_tier_id':name,'known_state':'KNOWN','amount':amount,
             'currency':'USD','availability':'AVAILABLE','fee_role':'APPLICATION'} for name,amount in [('Gold Sparrow','149'),('Silver Jay','49')]]
    data={'catalog':[{'tier_ref':p['ref'],'tier_name':p['ref']} for p in prices],
          'facts':[{'field':'prices','label':'Airline','value':prices}]}
    text=verified_activity_prices([{'data':data}],'Gold Sparrow 航空会籍申请费是多少')
    assert 'USD 149' in text and 'Silver Jay' not in text
    data['facts'].append({'field':'caveats','value':[{'known_state':'KNOWN','value':'Select Silver applicants may buy-up for an additional fee of USD $199.', 'evidence_ids':['evidence']}]})
    text=verified_activity_prices([{'data':data}],'49和199是什么费用')
    assert '199' in text and 'Select Silver applicants may' in text and '不是通用申请费' in text


def test_compound_route_question_returns_bound_document_requirements():
    r=route();r['step_refs']=['one']
    clause='Valid Canadian Passport required. ID Cards and Residence Permits not accepted.'
    steps={'one':{'from':'Aeroplan 50K','to':'Gold Sparrow','constraint_checks':[
        {'topic':'DOCUMENT_REQUIREMENT','reason':clause}]}}
    text=verified_route_text([r],search_complete=False,steps=steps,question='加拿大身份证能不能申请？')
    assert clause in text
    assert '要求居住' not in text


def test_validity_fallback_keeps_duration_anchor_without_extra_model():
    from journeyplus.agent.answer_grounding import verified_activity_validity
    material={'data':{'facts':[{'ref':'validity','field':'status_validity','label':'Avolta',
        'value':{'known_state':'KNOWN','value':{'kind':'DURATION','months':12,'anchor':'APPROVAL'}}}]}}
    assert verified_activity_validity([material,material])=='Avolta：批准后12 个月。'


def test_activity_price_answer_does_not_mix_old_and_current_versions():
    activity=str(uuid4());old=str(uuid4());current=str(uuid4())
    def material(version,amount):
        return {'data':{'activities':[{'ref':activity,'version_ref':version,'name':'Example'}],
            'catalog':[], 'facts':[{'field':'prices','label':'Application','value':[{
                'ref':version+'/price','target_tier_id':None,'known_state':'KNOWN','amount':amount,
                'currency':'USD','availability':'AVAILABLE','fee_role':'APPLICATION','conditions':{},'raw_text':''}]}]}}
    state={'current_question':'申请费多少','current_activity_refs':[activity],
        'activities':{activity:{'ref':activity,'version_ref':current,'name':'Example'}},
        'materials':[material(old,'99'),material(current,'149')]}
    refs=ReferenceMap(state);refs.encode(activity)
    result=WorkspaceService(None,None)._assemble({'text':'USD99','blocks':[],'next_steps':[]},state,refs)
    assert 'USD 149' in result['text'] and '99' not in result['text']
    assert len(result['blocks'])==1
