from journeyplus.agent.services.presentations import build_block
from journeyplus.agent.tools.contracts import BlockSelection


def route(ref, source, target, tier, paid=False, via=None):
    names=[source, *([via] if via else []), target]
    steps={str(i):{'from_tier_id':a,'to_tier_id':b,'from':a,'to':b,
        'target_program_key':'flying blue' if b==target else b,
        'target_tier_key':tier if b==target else 'gold','paid':paid,'version_ref':'v'}
        for i,(a,b) in enumerate(zip(names,names[1:]))}
    return {'ref':ref,'step_refs':list(steps),'steps':steps,'paid':paid,
            'query_sources':[{'tier_ref':source,'program_name':source,'tier_name':'Gold'}]}


def test_highest_tier_and_free_duplicate_across_selected_snapshots():
    objects=[route('low','A','S','silver'),route('paid','A','G','gold',True),route('free','B','G','gold')]
    block=build_block(BlockSelection(type='route_graph',object_refs=['low','paid','free']),objects)
    assert block['ordered_refs']==['free']
    assert block['object_count']==1
    obj=block['payload']['objects'][0]['data']
    assert obj['steps']['0']['from']=='B'
    assert {s['program_name'] for s in obj['query_sources']}=={'A','B'}
    assert objects[-1]['query_sources']==[{'tier_ref':'B','program_name':'B','tier_name':'Gold'}]


def test_lower_tier_is_kept_when_needed_as_intermediate():
    objects=[route('low','A','S','silver'),route('high','A','G','gold',via='S')]
    block=build_block(BlockSelection(type='route_graph',object_refs=['low','high']),objects)
    assert block['ordered_refs']==['high']
    assert [s['to'] for s in block['payload']['objects'][0]['data']['steps'].values()]==['S','G']


def test_comparison_has_fixed_binary_cost_and_steps_columns():
    block=build_block(BlockSelection(type='comparison',object_refs=['r']),[route('r','A','G','gold',True)])
    assert block['columns']==['cost','steps']
    assert block['payload']['objects'][0]['data']['paid']


def test_duplicate_object_ref_is_only_rendered_once():
    obj=route('r','A','G','gold')
    block=build_block(BlockSelection(type='route_graph',object_refs=['r','r']),[obj,obj])
    assert block['ordered_refs']==['r'] and block['object_count']==1


def test_agent_summary_uses_combined_origin_but_inspect_keeps_real_source():
    from journeyplus.agent.tools.routes import route_summary
    obj=route('r','Lufthansa Senator','G','gold')
    obj.update({'from':'Lufthansa Senator','to':'Gold','step_count':1,
        'source_group':{'label':'所选会籍组合','count':2}})
    summary=route_summary(obj,'artifact:test',obj['steps'])
    assert summary['from']=='所选会籍组合' and summary['path'][0]=='所选会籍组合'
    actual=route_summary(obj,'artifact:test',obj['steps'],detail=True)
    assert actual['from']=='Lufthansa Senator' and actual['path'][0]=='Lufthansa Senator'


def test_result_pagination_uses_actual_identity_not_combined_display_label():
    from journeyplus.agent.tools.routes import result_page
    obj=route('r','Lufthansa Senator','G','gold')
    obj.update({'from':'Lufthansa Senator','to':'Gold','step_count':1,
        'source_group':{'label':'所选会籍组合','count':2}})
    rows,cursor=result_page({'routes':{'r':obj},'steps':obj['steps'],'route_order':['r']},'artifact:test',0,20)
    assert len(rows)==1 and rows[0]['from']=='所选会籍组合' and cursor is None


def test_route_summary_omits_placeholders_but_preserves_real_caveat_access():
    from journeyplus.agent.tools.routes import route_summary
    obj={'ref':'r','step_refs':[],'paid':False,'cost':{'paid':False,'state':'KNOWN'},
         'eligibility':'UNKNOWN','challenge':'UNKNOWN','classification':'MATCH'}
    clean=route_summary(obj,'artifact:root',{})
    assert clean['paid'] is False
    assert not {'cost','eligibility','challenge','material_caveats','material_caveat_count','caveats_truncated','assessment_scope'} & clean.keys()
    obj['material_caveats']=['Actual condition']
    short=route_summary(obj,'artifact:root',{})
    assert short['needs_inspection'] and short['material_caveat_count']==1
    assert route_summary(obj,'artifact:root',{},detail=True)['material_caveats']==['Actual condition']


def test_display_route_keeps_version_entry_without_duplicate_brief_lists():
    from journeyplus.agent.services.route_objects import RouteObject
    obj=RouteObject('artifact:x#route:r','artifact:x',{'ref':'r','step_refs':['s'],'paid':True},
        {'s':{'from':'A','to':'B','paid':True,'activity_ref':'activity-id','version_ref':'version-id','brief_url':'/knowledge?activity_id=activity-id&version_ref=version-id&section=brief'}})
    value=obj.display_data()
    assert 'brief_links' not in value
    assert value['steps']['artifact:x#step:s']['version_ref']=='version-id'
    assert value['steps']['artifact:x#step:s']['brief_url']
