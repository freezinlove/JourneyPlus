from journeyplus.agent.read_basis import read_basis


def test_receipt_preserves_versions_and_coverage_without_source_or_report_bodies():
    packet={'status':'PARTIAL','snapshot_ref':'snapshot','coverage':{'search_complete':False,'observed_count':22,'returned_count':8},
            'data':{'steps':{str(i):{'version_ref':f'v{i}','raw_html':'PRIVATE SOURCE BODY'} for i in range(15)},
                    'reports':[{'body':'PRIVATE REPORT BODY'}],'reason_counts':{'known over budget':3}}}
    receipt=read_basis('query_membership_routes',packet)
    assert receipt['coverage']==packet['coverage'] and receipt['additional_version_count']==3
    assert len(receipt['version_refs'])==12 and receipt['filter_reasons']=={'known over budget':3}
    assert 'PRIVATE' not in str(receipt) and 'read_at' in receipt


def test_disabled_gate_does_not_fabricate_a_version_or_coverage():
    receipt=read_basis('research_statusmatcher',{'status':'DISABLED'})
    assert receipt['version_refs']==[] and receipt['coverage'] is None and receipt['snapshot_ref'] is None
