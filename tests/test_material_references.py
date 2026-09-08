from journeyplus.agent.material_references import material_refs,belongs_to_versions


def test_nested_price_and_evidence_are_owned_but_catalog_is_not():
    m={'data':{'activities':[{'ref':'a','version_ref':'v'}],'facts':[{'ref':'v/prices','value':[{'ref':'price','evidence_ids':['e']}]}],'catalog':[{'ref':'tier'}]}}
    assert material_refs(m)=={'a','v/prices','price','e'}
    assert belongs_to_versions('e',{'v'},[m])
    assert not belongs_to_versions('e',{'wrong'},[m])
    assert not belongs_to_versions('tier',{'v'},[m])


def test_evidence_cannot_cross_activity_versions():
    first={'data':{'activities':[{'ref':'a','version_ref':'v1'}],'facts':[{'ref':'v1/price','value':{'ref':'p1','evidence_ids':['e1']}}]}}
    second={'data':{'activities':[{'ref':'b','version_ref':'v2'}],'facts':[{'ref':'v2/price','value':{'ref':'p2','evidence_ids':['e2']}}]}}
    assert not belongs_to_versions('p1',{'v2'},[first,second])
    assert not belongs_to_versions('e2',{'v1'},[first,second])


def test_combined_envelope_keeps_nested_fact_ownership():
    m={'data':{'activities':[{'ref':'a','version_ref':'v1'},{'ref':'b','version_ref':'v2'}],
        'facts':[{'ref':'v1/prices','value':[{'ref':'price','evidence_ids':['e']}]}]}}
    assert belongs_to_versions('e',{'v1'},[m])
    assert not belongs_to_versions('e',{'v2'},[m])
