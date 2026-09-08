from journeyplus.agent.display_focus import focused_qualification


def test_clicked_node_narrows_qualification_to_its_visible_route():
    class Refs:
        def decode(self,value):return value
    state={'focus':{'ref':'node','presentation_id':'answer'},'nodes':{'node':{'step_refs':['rj-step']}},
           'steps':{'rj-step':{}},'routes':{'rj':{'step_refs':['rj-step']},'vn':{'step_refs':['vn-step']}},
           'presentations':[{'id':'answer','ordered_route_refs':['rj','vn']}]}
    assert focused_qualification(state,Refs(),'这个要什么证件？')=={'routes':['rj'],'steps':['rj-step']}
    assert focused_qualification(state,Refs(),'这个和其他方案比较一下条件') is None
    assert focused_qualification(state,Refs(),'换成越南航空有什么要求？') is None
    state['focus']['presentation_id']='missing'
    assert focused_qualification(state,Refs(),'这个要什么证件？') is None


def test_unambiguous_qualification_reuses_last_route_but_not_ambiguous_pair():
    class Refs:
        def decode(self,value):return value
    state={'routes':{'r':{'step_refs':['step']}},'presentations':[{'id':'a','ordered_route_refs':['r']}]}
    assert focused_qualification(state,Refs(),'这条路径还需要核实什么？')=={'routes':['r'],'steps':['step']}
    state['routes']['r2']={'step_refs':['s2']};state['presentations'][0]['ordered_route_refs'].append('r2')
    assert focused_qualification(state,Refs(),'这条路径还需要核实什么？') is None
    assert focused_qualification(state,Refs(),'核对这些已选路径的条件', ['r2'])=={'routes':['r2'],'steps':['s2']}
