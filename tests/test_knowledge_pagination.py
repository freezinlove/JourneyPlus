import json
from journeyplus.knowledge.pagination import store_search,continue_search
from journeyplus.knowledge.packets import decision_packet,encoded_bytes


def search_result():
    cards=[{'ref':f'route-{i}','step_refs':[f'step-{i}']} for i in range(12)]
    steps={f'step-{i}':{'ref':f'step-{i}','text':'完整步骤'} for i in range(12)}
    return {'schema_version':1,'status':'OK','snapshot_ref':'snapshot',
            'snapshot':{'activity':'version'},'data':{'query':{},'cards':cards[:8],'steps':steps},
            'coverage':{'search_complete':True,'observed_count':12},
            'server_routes':{c['ref']:c for c in cards},'server_steps':steps}


def test_pagination_preserves_all_candidates_across_workspace_reload():
    state={'routes':{},'steps':{}};first=store_search(state,search_result(),'query',now=10)
    assert len(first['data']['cards'])==8 and len(state['routes'])==12
    assert 'server_routes' not in first and 'route_cursor_key' not in first
    state=json.loads(json.dumps(state))
    second=continue_search(state,first['next_cursor'],current_snapshot={'activity':'version'},now=11)
    assert len(second['data']['cards'])==4 and second['next_cursor'] is None
    assert {c['ref'] for c in first['data']['cards']}.isdisjoint(c['ref'] for c in second['data']['cards'])
    assert second['coverage']['search_complete']


def test_cursor_rejects_tampering_changed_query_version_and_expiry():
    state={'routes':{},'steps':{}};page=store_search(state,search_result(),'query',now=10);cursor=page['next_cursor']
    for token,kwargs in [
        ('A'+cursor[1:],{'current_snapshot':{'activity':'version'},'now':11}),
        (cursor,{'current_snapshot':{'activity':'new-version'},'now':11}),
        (cursor,{'current_snapshot':{'activity':'version'},'query_hash':'different','now':11}),
        (cursor,{'current_snapshot':{'activity':'version'},'now':4000}),
    ]:
        assert continue_search(state,token,**kwargs)['status']=='EXPIRED'
    assert len(state['routes'])==12


def test_same_versions_but_changed_evaluation_context_invalidates_pagination():
    state={'routes':{},'steps':{}}
    page=store_search(state,search_result(),'query',now=10,evaluation_context='original')
    assert continue_search(state,page['next_cursor'],current_snapshot={'activity':'version'},now=11,evaluation_context='original')['status']=='OK'
    assert continue_search(state,page['next_cursor'],current_snapshot={'activity':'version'},now=11,evaluation_context='changed')['status']=='EXPIRED'
    assert len(state['routes'])==12


def test_packet_cannot_leak_server_cache_and_drops_unreferenced_steps():
    result=search_result()
    result['data']['cards']=list(result['server_routes'].values())
    for step in result['data']['steps'].values():step['text']='必须保留的完整限制。'*20
    packet=decision_packet(result,max_bytes=3000)
    assert 'server_routes' not in packet and 'server_steps' not in packet and 'snapshot' not in packet
    assert encoded_bytes(packet)<=3000
    used={sid for card in packet.get('data',{}).get('cards',[]) for sid in card['step_refs']}
    assert used
    assert set(packet.get('data',{}).get('steps',{}))==used
    assert packet['coverage']['search_complete']


def test_hidden_server_references_are_not_registered_as_disclosed_objects():
    from uuid import uuid4
    from journeyplus.knowledge.references import ReferenceMap
    hidden,visible,later=map(str,(uuid4(),uuid4(),uuid4()))
    state={};refs=ReferenceMap(state)
    packet=refs.encode_packet({'status':'OK','server_routes':{hidden:{}},'data':{'activities':[{'ref':visible}]}})
    assert hidden not in refs.reverse and visible in refs.reverse
    visible_ref=packet['data']['activities'][0]['ref']
    later_ref=refs.encode(later)
    assert later_ref!=visible_ref and refs.decode(visible_ref)==visible
    assert ReferenceMap(json.loads(json.dumps(state))).decode(visible_ref)==visible


def test_overview_shares_complete_limitations_and_temporals_without_mutating_server():
    from copy import deepcopy
    from journeyplus.knowledge.packets import project_model_packet
    result=search_result()
    caveat='Only earned status qualifies; matched status is not eligible.'
    temporal={'known_state':'KNOWN','value':{'precision':'RELATIVE','offset_days':90,
              'raw_text':'90 days after approval, unless cancelled earlier','evidence_ids':['proof']}}
    for card in result['data']['cards']:card['material_caveats']=[caveat]
    for step in result['data']['steps'].values():
        step.update(material_caveats=[caveat],application_window=temporal,status_validity=temporal,
                    constraint_checks=[{'result':'UNKNOWN','reason':caveat}])
    before=deepcopy(result);packet=project_model_packet(result);data=packet['data']
    assert result==before
    assert data['view']=='ROUTE_OVERVIEW' and list(data['material_caveats'].values())==[caveat]
    assert list(data['temporal_facts'].values())==[temporal]
    assert len(data['cards'])==8
    for step in data['steps'].values():
        assert data['temporal_facts'][step['status_validity_ref']]==temporal
        assert [data['material_caveats'][ref] for ref in step['material_caveat_refs']]==[caveat]
        assert 'constraint_checks' not in step
    assert project_model_packet(packet)==packet


def test_entire_tool_history_has_one_budget_and_preserves_atomic_conditions():
    from journeyplus.knowledge.packets import decision_packets
    condition='Only earned status qualifies; matched status is not eligible.'
    packets=[{'status':'OK','data':{'catalog':[{'name':'Same catalog'}],
              'facts':[{'ref':f'{i}-{j}','condition':condition,'notes':'x'*400} for j in range(7)]}}
             for i in range(3)]
    assert all(encoded_bytes(p)<5000 for p in packets)
    result=decision_packets(packets,max_bytes=5000)
    assert encoded_bytes(result)<=5000
    assert sum(bool(p.get('data',{}).get('catalog')) for p in result)<=1
    assert any(p['status'] in {'PARTIAL','NEEDS_INSPECTION'} for p in result)
    for packet in result:
        for fact in packet.get('data',{}).get('facts',[]):assert fact['condition']==condition
def test_oversized_atomic_packet_preserves_page_refs_or_disables_skipping():
    from journeyplus.knowledge.packets import decision_packet,encoded_bytes
    packet={'status':'OK','data':{'indivisible':{'rule':'x'*10000}},
            'coverage':{'search_complete':True},'next_cursor':'next-page',
            'expansions':[{'ref':f'route-{i}','kind':'ROUTE','reason':'x'*500} for i in range(8)]}
    result=decision_packet(packet,max_bytes=1500)
    assert {x['ref'] for x in result['expansions']}=={f'route-{i}' for i in range(8)}
    assert encoded_bytes(result)<=1500
    smaller=decision_packet(packet,max_bytes=600)
    assert encoded_bytes(smaller)<=600
    if len(smaller['expansions'])<8:
        assert smaller['next_cursor'] is None
        assert smaller['coverage']['undisclosed_reference_count']==8-len(smaller['expansions'])
