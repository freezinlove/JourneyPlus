import asyncio
from journeyplus.agent.harness.contracts import Capabilities, ToolDefinition, ToolResult
from journeyplus.agent.harness.budget import Budget
from tests.test_harness_runtime import FakeModel, Echo, call, answer, execute


def test_more_than_old_request_and_tool_limits(session_factory):
    seen=[]
    async def handler(args,ctx):
        seen.append(args.value)
        return ToolResult(data={'value':args.value})
    batches=[call(value=str(i),id=str(i)) for i in range(30)]+[answer()]
    for batch in batches:batch.insert(-1,{'type':'usage','usage':{'input':100000,'output':1000}})
    model=FakeModel(batches)
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler)])
    assert len(seen)==30 and len(model.inputs)==31
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_large_parallel_batch_returns_whole_results(session_factory):
    class Model(FakeModel):
        def capabilities(self):return Capabilities(native_tools=True,streaming=True,context_window=1000000,max_output=4096)
    body='完整业务信息'*1800
    seen=[]
    async def handler(args,ctx):
        seen.append(args.value)
        return ToolResult(data={'body':body,'identity':args.value})
    batch=[call(value=str(i),id=str(i))[0] for i in range(10)]+[{'type':'turn_end','finish_reason':'tool_calls'}]
    model=Model([batch,answer()])
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler)])
    results=[p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result']
    assert len(seen)==10 and len(results)==10
    assert all(r['data']['body']==body and not r['error'] for r in results)
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_only_elapsed_time_stops_budget():
    budget=Budget(requests=500,tools=500,input_tokens=9000000,output_tokens=9000000)
    assert not budget.reached('hard')
    assert budget.limits(Capabilities(native_tools=True,streaming=True,context_window=1000000,max_output=131072))['max_output']==131072
    budget.started-=181
    assert budget.reached('hard')


def test_long_reply_is_not_rejected_by_display_schema():
    from journeyplus.agent.tools.contracts import DisplayInput
    assert len(DisplayInput(answer='长回答'*4000,blocks=[],next_steps=[{'label':'下一步','message':'继续'}]).answer)==12000


def test_record_reads_keep_whole_business_objects():
    from journeyplus.agent.services.artifact_views import view
    value={'conditions':'完整条件'*3000,'amount':'99','currency':'USD'}
    result=view([{'ref':'artifact:one','payload':value}])
    assert result['artifacts'][0]['payload']==value
    assert result['next_cursor'] is None


def test_mapping_matrix_keeps_distinct_conditions_and_all_tiers():
    from journeyplus.agent.services.mapping_table import mapping_table
    rows=[{'source_program':'A','source_tiers':['Gold'],'target_tier':'Silver','conditions':'x'},
          {'source_program':'A','source_tiers':['Platinum'],'target_tier':'Silver','conditions':'x'},
          {'source_program':'A','source_tiers':['Gold'],'target_tier':'Gold','conditions':'y'}]
    table=mapping_table(rows)
    assert table['columns']==['来源项目','Silver','Gold']
    assert table['rows'][0][1]==[{'tiers':['Gold','Platinum'],'conditions':'x'}]
    assert table['rows'][0][2]==[{'tiers':['Gold'],'conditions':'y'}]
    assert table['mapping_count']==3


def test_registered_mapping_read_and_direct_display(session_factory,original_factory):
    from tests.test_agent_workflow_reads import context,seed,call as invoke
    identity=seed(original_factory)
    runtime,store,ctx=context(session_factory,original_factory)
    result=invoke(runtime,ctx,'activity.read',{'selector':{'ref':f'activity:{identity}'},'view':'mappings','limit':1})
    record=result.data['activities'][0]
    assert record['mapping_table']['columns'][0]=='来源项目'
    assert record['mapping_table']['mapping_count']>0
    displayed=invoke(runtime,ctx,'display.present',{'blocks':[{'type':'mapping_table','object_refs':[record['ref']]}],'complete':True})
    assert displayed.data['blocks'][0]['type']=='mapping_table'
    assert 'mapping_table' not in str(displayed.data.get('answer'))
    full=store.artifacts.read(ctx.workspace_id,displayed.data['presentation_ref'])['payload']
    assert full['blocks'][0]['payload']['objects'][0]['data']['options'][0]['mappings']
    asyncio.run(runtime.services['research'].close())


from tests.test_agent_workflow_reads import original_factory


def test_route_default_page_has_no_count_or_byte_cap():
    from journeyplus.agent.tools.contracts import RoutesInput
    from journeyplus.agent.tools.routes import result_page,capacity_page
    args=RoutesInput(operation='search',query={'sources':{'mode':'saved'}})
    assert args.limit is None
    routes={str(i):{'ref':str(i),'step_refs':[],'description':'详细路径'*1000} for i in range(25)}
    payload={'routes':routes,'route_order':list(routes)}
    rows,cursor=result_page(payload,'artifact:routes',0,args.limit)
    assert len(rows)==25 and cursor is None
    result=ToolResult(data={'query_ref':'artifact:query','candidates':rows,'route_refs':[r['ref'] for r in rows]},coverage={'total':25,'offset':0,'page_offset':0,'complete':True})
    small=capacity_page(result)
    assert len(small.data['candidates'])==12 and small.next_cursor=='artifact:routes|12'
    assert small.coverage['unread_candidate_count']==13
    assert small.data['candidates']==rows[:12]
    remaining,following=result_page(payload,'artifact:routes',12,None)
    assert remaining==rows[12:] and following is None
    assert len(result.data['candidates'])==25


def test_context_pressure_drops_whole_old_turn_without_clipping_results():
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    old={'data':{'body':'older'*5000},'artifact_refs':['artifact:old']}
    current={'data':{'body':'current'*2000},'artifact_refs':['artifact:current']}
    messages=[ModelMessage(role='user',content=[Part(type='text',text='old')]),
        ModelMessage(role='assistant',content=[Part(type='tool_call',name='echo',call_id='old',arguments={})]),
        ModelMessage(role='tool',content=[Part(type='tool_result',call_id='old',result=old)]),
        ModelMessage(role='user',content=[Part(type='text',text='new')]),
        ModelMessage(role='assistant',content=[Part(type='tool_call',name='echo',call_id='new',arguments={})]),
        ModelMessage(role='tool',content=[Part(type='tool_result',call_id='new',result=current)])]
    out=project(messages,[],Capabilities(native_tools=True,streaming=True,context_window=100000,max_output=1000),context_token_budget=8000)
    results=[p for m in out for p in m.content if p.type=='tool_result']
    assert len(results)==1 and results[0].result==current
    assert messages[2].content[0].result==old
    assert any('history_available_before' in (p.text or '') for m in out for p in m.content)


def test_actual_context_pressure_pages_whole_candidates(session_factory):
    from journeyplus.agent.tools.routes import capacity_page
    class Model(FakeModel):
        def capabilities(self):return Capabilities(native_tools=True,streaming=True,context_window=12000,max_output=1024)
    rows=[{'ref':f'artifact:routes#route:{i}','path':['A',str(i)],'description':'完整内容'*700} for i in range(20)]
    async def handler(args,ctx):
        return ToolResult(data={'query_ref':'artifact:query','candidates':rows,'route_refs':[r['ref'] for r in rows]},coverage={'total':20,'offset':0,'page_offset':0,'complete':True})
    model=Model([call(value='routes'),answer()])
    store,w,r=execute(session_factory,model,[ToolDefinition('echo','Echo',Echo,handler,capacity_page=capacity_page)])
    result=next(p.result for m in model.inputs[-1] for p in m.content if p.type=='tool_result')
    count=len(result['data']['candidates'])
    assert 0<count<20 and result['data']['candidates']==rows[:count]
    assert result['next_cursor']==f'artifact:routes|{count}'
    assert result['coverage']['pagination_reason']=='context_capacity'
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'


def test_storage_chunks_do_not_force_model_pages():
    from journeyplus.agent.tools.routes import result_page,capacity_page
    first={'routes':{'a':{'ref':'a','step_refs':[]}},'route_order':['a'],'next_result_ref':'artifact:second'}
    second={'routes':{str(i):{'ref':str(i),'step_refs':[]} for i in range(5)},'route_order':[str(i) for i in range(5)]}
    rows,cursor=result_page(first,'artifact:first',0,None,lambda ref:second)
    assert len(rows)==6 and cursor is None
    r=ToolResult(data={'query_ref':'artifact:q','candidates':rows},coverage={'total':6,'offset':0,'page_offset':0})
    small=capacity_page(r)
    assert small.next_cursor=='artifact:second|2'
    rest,cursor=result_page(second,'artifact:second',2,None)
    assert small.data['candidates']+rest==rows and cursor is None
