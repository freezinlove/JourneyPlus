import ast
from pathlib import Path
import pytest
from pydantic import ValidationError
from journeyplus.agent.harness.contracts import DTO, ToolDefinition, ToolResult
from journeyplus.agent.harness.registry import Registry
from journeyplus.agent.harness.budget import estimate
from journeyplus.agent.tools.contracts import INPUTS, RoutesInput, IdentityName, DisplayInput


def test_harness_dependency_boundary():
    root=Path(__file__).parents[1]/'src/journeyplus/agent/harness'
    for path in root.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            for name in names:
                assert not name.startswith(('sqlalchemy','journeyplus.knowledge','journeyplus.membership','journeyplus.product','journeyplus.agent.workspace','journeyplus.agent.controller','journeyplus.agent.tools','journeyplus.agent.services','journeyplus.agent.adapters')), (path,name)


def test_all_tools_reject_owner_and_unknown_arguments():
    assert len(INPUTS)==12
    for model in INPUTS.values():
        assert model.model_json_schema()['additionalProperties'] is False
        with pytest.raises(ValidationError):model.model_validate({'owner':'model-controlled'})
    with pytest.raises(ValidationError):IdentityName(program_name='Example',ref='forged')


def test_routes_require_explicit_query_shape():
    with pytest.raises(ValidationError):RoutesInput(operation='search')
    with pytest.raises(ValidationError):RoutesInput(operation='search',query={'sources':{'mode':'saved','identities':[{'program_name':'X'}]}})
    with pytest.raises(ValidationError):RoutesInput(operation='inspect',query={'sources':{'mode':'none'}})
    assert RoutesInput(operation='search',query_ref='artifact:x',patch={'target':None}).patch.model_dump(exclude_unset=True)=={'target':None}


def test_display_preserves_order_and_rejects_false_roles():
    value=DisplayInput(blocks=[{'type':'route_graph','object_refs':['B','A']}])
    assert value.blocks[0].object_refs==['B','A']
    with pytest.raises(ValidationError):DisplayInput(blocks=[{'type':'route_graph','object_refs':['A'],'roles':[{'ref':'B','role':'primary'}]}])


def test_registry_is_extensible_and_reports_unknown_tool():
    class Echo(DTO):value:str
    async def echo(args,context):return ToolResult(data={'value':args.value})
    registry=Registry();registry.register(ToolDefinition('echo','Echo a value',Echo,echo))
    validated,error=registry.validate('echo',{'value':'hi'})
    assert not error and validated[1].value=='hi'
    assert registry.validate('missing',{})[1].error.code=='UNKNOWN_TOOL'
    assert registry.validate('echo',{'value':'hi','owner':'forged'})[1].error.code=='INVALID_ARGUMENT'


def test_tools_schema_budget():
    definitions=[{'name':name,'parameters':model.model_json_schema()} for name,model in INPUTS.items()]
    # UTF8 estimate is deliberately conservative; diagnostic until provider actual usage measured.
    assert estimate(definitions)<8000


def test_bounded_detail_keeps_object_reference_and_marks_omission():
    from journeyplus.agent.harness.context import bounded_result
    from journeyplus.agent.harness.contracts import ToolResult
    original=ToolResult(data={'activities':[{'ref':'activity:abc@version','material_ref':'artifact:abc','title':'An activity','facts':[{'value':'Long fact '+str(i)*100,'ref':str(i)} for i in range(100)]}]})
    bounded=bounded_result(original,'artifact:full',2400)
    assert bounded.data['activities'][0]['ref']=='activity:abc@version'
    assert bounded.coverage['complete'] is False
    assert bounded.coverage['full_result_ref']=='artifact:full'
    assert len(bounded.model_dump_json().encode())<3000
    assert len(original.data['activities'][0]['facts'])==100


def test_registry_keeps_missing_reference_and_output_errors_distinct():
    import asyncio
    from time import monotonic
    from journeyplus.agent.harness.contracts import DTO,ToolDefinition,ExecutionContext
    from journeyplus.agent.harness.registry import Registry
    class Input(DTO):pass
    async def missing(args,ctx):raise LookupError('Artifact missing or outside workspace')
    async def malformed(args,ctx):return {'status':'invented','data':{}}
    registry=Registry()
    registry.register(ToolDefinition('missing','Lookup',Input,missing))
    registry.register(ToolDefinition('malformed','Bad implementation',Input,malformed))
    ctx=ExecutionContext('w','t','c','u',monotonic()+20,asyncio.Event(),None,None,{})
    first=asyncio.run(registry.execute(registry.validate('missing',{})[0],ctx))
    second=asyncio.run(registry.execute(registry.validate('malformed',{})[0],ctx))
    assert first.status=='NOT_FOUND' and first.error.code=='NOT_FOUND'
    assert second.error.code=='INVALID_TOOL_RESULT'


def test_context_recent_window_counts_dialogue_not_tool_progress_messages():
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part,Capabilities
    history=[ModelMessage(role='user',content=[Part(type='text',text='My temporary source is Example Gold; target Other Program')])]
    for index in range(12):
        history.append(ModelMessage(role='assistant',content=[Part(type='text',text='Reading the next item.'),Part(type='tool_call',call_id=str(index),name='echo',arguments={})]))
        history.append(ModelMessage(role='tool',content=[Part(type='tool_result',call_id=str(index),result={'data':{'value':index}})]))
    history.append(ModelMessage(role='assistant',content=[Part(type='text',text='The available result has limits.')]))
    history.append(ModelMessage(role='user',content=[Part(type='text',text='What about another source?')]))
    projected=project(history,[],Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=2048))
    assert projected[0].id==history[0].id
    assert len([p for message in projected for p in message.content if p.type=='tool_call'])==12
    assert len([p for message in projected for p in message.content if p.type=='tool_result'])==12


def test_projection_caps_large_scalars_and_metadata_with_expandable_reference():
    from journeyplus.agent.harness.context import bounded_result
    from journeyplus.agent.harness.contracts import ToolResult
    ref='artifact:00000000-0000-0000-0000-000000000001'
    original=ToolResult(data={'text':'很长的原始条款'*30000},provenance=[{'text':'large'*5000}])
    projected=bounded_result(original,ref,max_bytes=2400)
    assert len(projected.model_dump_json().encode())<=2400
    assert projected.coverage['complete'] is False and projected.coverage['full_result_ref']==ref
    assert original.data['text']=='很长的原始条款'*30000


def test_projection_never_removes_parts_inside_retained_entries():
    from journeyplus.agent.harness.context import bounded_result
    from journeyplus.agent.harness.contracts import ToolResult
    entries=[{'id':i,'path':['Source','Intermediate','Target'],
              'cost':{'totals':[{'amount':'49','currency':'USD'},{'amount':'149','currency':'USD'}]},
              'text':'detail '*150} for i in range(10)]
    result=bounded_result(ToolResult(data={'candidates':entries}),'artifact:full',2400)
    assert result.coverage['complete'] is False
    for entry in result.data.get('candidates',[]):
        assert entry==entries[entry['id']]


def test_each_tool_declares_and_enforces_its_own_result_data_schema():
    import pytest
    from pydantic import ValidationError
    from journeyplus.agent.tools.results import OUTPUTS
    assert len(OUTPUTS)==12
    for output in OUTPUTS.values():
        with pytest.raises(ValidationError):output.model_validate({'data':{'unexpected_field':True}})
        with pytest.raises(ValidationError):output.model_validate({'status':'OK','data':{}})
        output.model_validate({'status':'ERROR','error':{'code':'TEST','message':'Failure'}})
    OUTPUTS['holdings.write'].model_validate({'data':{'operation_ref':'operation:receipt','outcome':'APPLIED'}})


def test_notes_respect_context_token_budget():
    import pytest
    from journeyplus.agent.tools.contracts import NoteInput
    with pytest.raises(ValueError):NoteInput(expected_revision=0,content='长'*3000)
    assert NoteInput(expected_revision=0,content='A short note with source references').content


def test_history_preserves_original_results_and_user_conditions():
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part,Capabilities
    history=[]
    originals=[]
    for turn in range(3):
        history.append(ModelMessage(role='user',content=[Part(type='text',text=f'Exact user condition {turn}')]))
        for page in range(2):
            call=f'{turn}-{page}'
            result=ToolResult(data={'effective_query':{'source':str(turn)},
                'candidates':[{'path':['Source','Middle','End'],'cost':{'state':'UNKNOWN'},'text':'data '*200}]},
                artifact_refs=['artifact:'+call]).model_dump(mode='json')
            originals.append(result)
            history.extend([ModelMessage(role='assistant',content=[Part(type='tool_call',call_id=call,name='lookup',arguments={})]),
                            ModelMessage(role='tool',content=[Part(type='tool_result',call_id=call,result=result)])])
        if turn<2:history.append(ModelMessage(role='assistant',content=[Part(type='text',text='Previous answer')]))
    selected=project(history,[],Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=2048))
    assert [m.content[0].text for m in selected if m.role=='user']==[f'Exact user condition {i}' for i in range(3)]
    results=[p.result for m in selected for p in m.content if p.type=='tool_result']
    assert results==originals
    assert not any(m.metadata.get('context_projection') for m in selected)
    assert all('candidates' in r['data'] for r in originals)


def test_history_keeps_exact_objects_prices_and_unknowns_from_each_page():
    import json
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part,Capabilities
    messages=[ModelMessage(role='user',content=[Part(type='text',text='All candidates')])]
    for number in range(2):
        call=str(number)
        messages.extend([ModelMessage(role='assistant',content=[Part(type='tool_call',call_id=call,name='lookup',arguments={})]),
            ModelMessage(role='tool',content=[Part(type='tool_result',call_id=call,result=ToolResult(
                data={'candidates':[{'ref':'artifact:root#object:'+call,'path':['Start','End '+call],
                                     'cost':{'state':'PARTIAL','known_subtotal':[{'amount':'999'}]}}]},
                artifact_refs=['artifact:page'+call]).model_dump(mode='json'))])])
    messages.append(ModelMessage(role='user',content=[Part(type='text',text='Details of the first object')]))
    selected=project(messages,[],Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096))
    results=[p.result for m in selected for p in m.content if p.type=='tool_result']
    for i,result in enumerate(results):
        item=result['data']['candidates'][0]
        assert item['ref']=='artifact:root#object:'+str(i)
        assert item['cost']=={'state':'PARTIAL','known_subtotal':[{'amount':'999'}]}
    assert len(results)==2


def test_history_preserves_last_search_scope_after_inspect_and_explicit_reset():
    import json
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part,Capabilities
    for target in ({'program_name':'Destination'},None):
        query={'sources':{'mode':'explicit','identities':[{'program_name':'Source','tier_name':'Gold'}]},'target':target}
        messages=[ModelMessage(role='user',content=[Part(type='text',text='Change destination')])]
        data=[{'query_ref':'artifact:old-query','effective_query':{'target':{'tier_name':'Old'}}},
              {'query_ref':'artifact:new-query','effective_query':query},
              {'candidates':[{'ref':'artifact:route','path':['Source','Destination']}]}]
        for number,value in enumerate(data):
            call=str(number)
            messages.extend([ModelMessage(role='assistant',content=[Part(type='tool_call',call_id=call,name='routes.evaluate',arguments={})]),
                ModelMessage(role='tool',content=[Part(type='tool_result',call_id=call,result=ToolResult(data=value,artifact_refs=['artifact:result'+call]).model_dump(mode='json'))])])
        messages.append(ModelMessage(role='user',content=[Part(type='text',text='Change source')]))
        selected=project(messages,[],Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096))
        results=[p.result['data'] for m in selected for p in m.content if p.type=='tool_result']
        assert results==data
        assert results[1]['effective_query']==query
        assert results[1]['query_ref']=='artifact:new-query'
        assert 'effective_query' not in results[2]


def test_operation_fields_cannot_be_silently_ignored():
    from journeyplus.agent.tools.contracts import HoldingsWriteInput,WaitingInput
    authorization={'message_refs':['message'],'quotes':['authorized']}
    base={'authorization':authorization,'operation_key':'operation'}
    for invalid in [
        {'operation':'delete','holding_ref':'holding:id','expected_revision':1,'identity':{'program_name':'X'}},
        {'operation':'delete','holding_ref':'holding:id','expected_revision':1,'valid_until':None},
        {'operation':'update','holding_ref':'holding:id','expected_revision':1},
        {'operation':'create','identity':{'program_name':'X'},'expected_revision':3},
        {'operation':'create','identity':{'program_name':'X'},'valid_until':'2027-02-30'},
    ]:
        with pytest.raises(ValidationError):HoldingsWriteInput(**base,**invalid)
    assert HoldingsWriteInput(**base,operation='update',holding_ref='holding:id',expected_revision=1,valid_until=None).valid_until is None
    for invalid in [
        {'operation':'list','query':{'sources':{'mode':'none'}}},
        {**base,'operation':'cancel','goal_ref':'goal:id','expected_revision':1,'query_ref':'artifact:query'},
        {**base,'operation':'create','goal_ref':'goal:id','query':{'sources':{'mode':'none'}}},
    ]:
        with pytest.raises(ValidationError):WaitingInput(**invalid)


def test_large_prior_result_uses_explicit_index_without_mutating_current_or_history():
    from copy import deepcopy
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ModelMessage,Part,Capabilities
    raw=ToolResult(data={'records':[{'ref':'artifact:object','qualification':'UNKNOWN','text':'evidence '*2000}]},
                   artifact_refs=['artifact:full']).model_dump(mode='json')
    messages=[ModelMessage(role='user',content=[Part(type='text',text='Only the specified source, do not save')]),
              ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='one',name='read',arguments={})]),
              ModelMessage(role='tool',content=[Part(type='tool_result',call_id='one',result=raw)]),
              ModelMessage(role='user',content=[Part(type='text',text='Now compare the previous source')]),
              ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='two',name='read',arguments={})]),
              ModelMessage(role='tool',content=[Part(type='tool_result',call_id='two',result=raw)])]
    original=[message.model_dump() for message in messages]
    selected=project(messages,[],Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096))
    results=[part.result for message in selected for part in message.content if part.type=='tool_result']
    assert results[0]['coverage']['complete'] is False and results[0]['data']['full_result_ref']=='artifact:full'
    assert results[0]['data']['records'][0]=={'ref':'artifact:object','projection':'index_only'}
    assert results[1]==raw and [message.model_dump() for message in messages]==original
    assert [message.content[0].text for message in selected if message.role=='user']==[
        'Only the specified source, do not save','Now compare the previous source']


def test_failed_tool_does_not_claim_complete_default_coverage():
    result=ToolResult(status='NOT_FOUND',error={'code':'CATALOG_GAP','message':'Source missing'})
    assert result.coverage=={'complete':False,'returned':0,'total':None,'omissions':['operation_not_completed']}
