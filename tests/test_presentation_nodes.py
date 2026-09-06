from journeyplus.agent.presentation_nodes import presentation_nodes


def test_shared_target_node_preserves_each_incoming_option_and_history():
    routes=[{'ref':'r1','step_refs':['direct']},{'ref':'r2','step_refs':['middle','last']}]
    steps={key:{'from':source,'to':target,'from_tier_id':source,'to_tier_id':target} for key,source,target in [
        ('direct','A','B'),('middle','A','C'),('last','C','B')]}
    nodes=presentation_nodes(routes,steps)
    b=next(n for n in nodes.values() if n['tier_ref']=='B')
    assert b['step_refs']==['direct','last']
    assert len(nodes)==2
    changed=presentation_nodes([{'ref':'r3','step_refs':['direct']}],steps)
    assert b['ref'] not in changed
