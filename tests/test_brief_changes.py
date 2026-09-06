from copy import deepcopy
from journeyplus.knowledge.brief_changes import changes_between


def example():
    return {'version_ref':'v1','facts':{},'options':[{'logical_ref':'airline','ref':'o1','label':'Airline match','prices':[{'ref':'p1','known_state':'KNOWN','amount':'149','currency':'USD','target_tier_id':'gold','fee_role':'APPLICATION','availability':'AVAILABLE'}],'mappings':[{'ref':'m1','target_tier_id':'gold','to_tier':'Gold','from_tier':'Elite'}],'conditions':{},'challenge':{},'application_window':{},'status_validity':{},'availability':'AVAILABLE'}]}


def test_change_brief_has_bound_old_new_price_scope_and_impact():
    old=example();new=deepcopy(old);new['version_ref']='v2';new['options'][0]['ref']='o2';new['options'][0]['prices'][0]['amount']='199'
    changes=changes_between(old,new)
    assert len(changes)==1
    change=changes[0]
    assert change['before_version_ref']=='v1' and change['after_version_ref']=='v2'
    assert change['before']['items'][0]['amount']=='149' and change['after']['items'][0]['amount']=='199'
    assert change['after']['items'][0]['target']=='Gold' and '预算' in change['impact']


def test_evidence_reference_or_order_only_changes_are_not_news():
    old=example();new=deepcopy(old);new['options'][0]['prices'][0].update(ref='p2',evidence_ids=['new-evidence'])
    new['options'][0]['mappings'][0]['ref']='m2'
    assert changes_between(old,new)==[]


def test_large_mapping_change_preview_is_bounded_and_explicit():
    old=example();new=deepcopy(old)
    new['options'][0]['mappings']=[{'from_tier':f'Source {i}','to_tier':'Gold'} for i in range(100)]
    change=changes_between(old,new)[0]
    assert change['after']['count']==100 and len(change['after']['items'])==6 and change['after']['omitted']==94


def test_same_source_condition_correction_is_not_an_official_rule_change():
    old=example();old['facts']['conditions']={'items':[{'topic':'RESIDENCY','raw_text':'Passport required.'}]}
    new=deepcopy(old);new['facts']['conditions']['items'][0]['topic']='DOCUMENT_REQUIREMENT'
    change=changes_between(old,new)[0]
    assert change['change']=='INTERPRETATION_UPDATED'
    assert '不代表官方' in change['impact']
    assert '居住地条件' in change['before'] and '证件要求' in change['after']
