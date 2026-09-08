import asyncio,json
import httpx
import pytest
from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import AgentModel
from journeyplus.agent.harness.contracts import ModelMessage,Part


def native_response(chunks):
    return httpx.Response(200,text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n')


def test_native_complete_parameters_and_usage():
    async def scenario():
        chunks=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'echo','arguments':'{"value":'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"ok"}'}}]},'finish_reason':'tool_calls'}]},
                {'choices':[],'usage':{'prompt_tokens':100,'completion_tokens':20}}]
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(lambda req:native_response(chunks)))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='native'
        events=[e async for e in model.stream([],[],{},asyncio.Event())]
        assert [e.arguments for e in events if e.type=='tool_call_ready']==[{'value':'ok'}]
        assert [e.usage for e in events if e.type=='usage']==[{'prompt_tokens':100,'completion_tokens':20}]
        await client.aclose()
    asyncio.run(scenario())


def test_native_namespace_names_roundtrip_without_suffix_guessing():
    from journeyplus.agent.harness.contracts import DTO,ToolDefinition
    from journeyplus.agent.adapters.model import native_names
    class Input(DTO):value:str
    definitions=[ToolDefinition(name,name,Input,None) for name in ['first.read','second.read','first_read']]
    names=native_names(definitions)
    assert len(set(names.values()))==3
    assert names==native_names(list(reversed(definitions)))
    assert all('.' not in name and len(name)<=64 for name in names.values())
    async def scenario():
        payloads=[]
        def respond(req):
            payloads.append(json.loads(req.content))
            return native_response([{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'new',
                'function':{'name':names['second.read'] if len(payloads)==1 else 'read','arguments':'{"value":"new"}'}}]},'finish_reason':'tool_calls'}]}])
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(respond))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='native'
        history=[ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='old',name='first.read',arguments={'value':'old'})]),
                 ModelMessage(role='tool',content=[Part(type='tool_result',call_id='old',result={'value':'old'})])]
        events=[event async for event in model.stream(history,definitions,{},asyncio.Event())]
        assert next(e.name for e in events if e.type=='tool_call_ready')=='second.read'
        assert payloads[0]['messages'][0]['tool_calls'][0]['function']['name']==names['first.read']
        assert {x['function']['name'] for x in payloads[0]['tools']}==set(names.values())
        unknown=[event async for event in model.stream(history,definitions,{},asyncio.Event())]
        assert next(e.name for e in unknown if e.type=='tool_call_ready')=='read'
        await client.aclose()
    asyncio.run(scenario())


def test_native_broken_stream_never_emits_ready():
    async def scenario():
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(lambda req:native_response([
            {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'echo','arguments':'{"value":"ok"}'}}]}}]}])))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='native'
        events=[]
        with pytest.raises(ValueError):
            async for e in model.stream([],[],{},asyncio.Event()):events.append(e)
        assert not any(e.type=='tool_call_ready' for e in events)
        await client.aclose()
    asyncio.run(scenario())


def test_native_final_request_omits_definitions_but_keeps_call_result_evidence():
    from journeyplus.agent.harness.contracts import DTO,ToolDefinition
    class Input(DTO):value:str
    definition=ToolDefinition('evidence.read','Read evidence',Input,None)
    history=[ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='one',name=definition.name,arguments={'value':'x'})]),
             ModelMessage(role='tool',content=[Part(type='tool_result',call_id='one',result={'data':{'qualification':'UNKNOWN','version':'v1'}})])]
    async def scenario():
        payloads=[]
        def respond(request):
            payloads.append(json.loads(request.content))
            return native_response([{'choices':[{'delta':{'content':'Evidence retained'},'finish_reason':'stop'}]}])
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(respond))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='native'
        assert model.estimate_final_input(history,[definition])<model.estimate_input(history,[definition])
        _=[event async for event in model.stream(history,[definition],{'tools_allowed':False},asyncio.Event())]
        assert 'tools' not in payloads[0]
        assert payloads[0]['tool_choice']=='none'
        assert payloads[0]['messages'][0]['tool_calls'][0]['function']['name']=='evidence_read'
        assert json.loads(payloads[0]['messages'][1]['content'])['data']=={'qualification':'UNKNOWN','version':'v1'}
        await model.close()
    asyncio.run(scenario())


def test_json_actions_normalize_same_call_and_answer():
    async def scenario():
        replies=iter([{'calls':[{'id':'c','name':'echo','arguments':{'value':'ok'}}],'finished':False},
                      {'message':'ok','finished':True}])
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(next(replies))}}]})))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='json'
        a=[e async for e in model.stream([],[],{},asyncio.Event())]
        b=[e async for e in model.stream([],[],{},asyncio.Event())]
        assert a[0].type=='tool_call_ready' and a[0].call_id=='c'
        assert b[0].text=='ok' and b[-1].finish_reason=='stop'
        assert model.capabilities().streaming is False
        await client.aclose()
    asyncio.run(scenario())


def test_json_history_keeps_user_roles_and_qualifies_reused_call_id():
    async def scenario():
        payloads=[]
        def respond(req):
            payloads.append(json.loads(req.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'calls':[{'id':'c','name':'echo','arguments':{'value':'second'}}],'finished':False})}}]})
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(respond))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='json'
        history=[ModelMessage(role='system',content=[Part(type='text',text='System rules')]),
                 ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='c',name='echo',arguments={'value':'first'})]),
                 ModelMessage(role='tool',content=[Part(type='tool_result',call_id='c',result={'value':'first'})]),
                 ModelMessage(role='user',content=[Part(type='text',text='Change the source')])]
        events=[e async for e in model.stream(history,[],{},asyncio.Event())]
        assert events[0].call_id!='c' and events[0].call_id.endswith(':c')
        assert payloads[0]['messages'][1]=={'role':'system','content':'System rules'}
        assert payloads[0]['messages'][-1]['role']=='user'
        assert 'Change the source' in payloads[0]['messages'][-1]['content']
        await client.aclose()
    asyncio.run(scenario())


def test_incomplete_json_response_never_exposes_text_or_calls():
    async def scenario():
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{"message":"fake complete","finished":true}'}}]})))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol='json'
        events=[]
        with pytest.raises(ValueError):
            async for event in model.stream([],[],{},asyncio.Event()):events.append(event)
        assert events==[]
        await client.aclose()
    asyncio.run(scenario())


def test_native_schema_preserves_nullable_objects_and_identity_union():
    from journeyplus.agent.adapters.model import inline_schema
    from journeyplus.agent.tools.contracts import RoutesInput
    schema=inline_schema(RoutesInput.model_json_schema())
    query=next(c for c in schema['properties']['query']['anyOf'] if c.get('type')=='object')
    assert query['type']=='object' and 'sources' in query['properties']
    identity=query['properties']['sources']['properties']['identities']['items']
    assert len(identity['anyOf'])==2
    assert identity['anyOf'][0]['required']==['ref']
    assert identity['anyOf'][1]['required']==['program_name']
    # The canonical boundary remains strict: a JSON-encoded object isn't input.
    import pytest
    with pytest.raises(ValueError):RoutesInput(operation='search',query='{"sources":{"mode":"none"}}')


def test_wire_schema_can_express_authorized_date_clear():
    from journeyplus.agent.adapters.model import inline_schema
    from journeyplus.agent.tools.contracts import HoldingsWriteInput
    schema=inline_schema(HoldingsWriteInput.model_json_schema())
    date=schema['properties']['valid_until']
    assert {'type':'null'} in date['anyOf']
    args={'operation':'update','holding_ref':'holding:example','expected_revision':1,
          'valid_until':None,'authorization':{'message_refs':['message'],'quotes':['clear expiry']},'operation_key':'clear'}
    parsed=HoldingsWriteInput.model_validate(args)
    assert 'valid_until' in parsed.model_fields_set and parsed.valid_until is None


def test_wire_container_decoding_preserves_values_and_canonical_validation():
    from journeyplus.agent.adapters.model import decode_wire_containers
    from journeyplus.agent.tools.contracts import RoutesInput,HoldingsWriteInput
    query={'sources':{'mode':'explicit','identities':[{'program_name':'Example','tier_name':'Gold'}]},
           'target':{'program_name':'Destination'},'constraints':{'free_only':False,'allow_challenge':None}}
    original={'operation':'search','query':json.dumps(query)}
    normalized,paths=decode_wire_containers(original,RoutesInput.model_json_schema())
    assert normalized=={'operation':'search','query':query} and paths==['/query']
    assert isinstance(original['query'],str)
    assert RoutesInput.model_validate(normalized).query.target.tier_name is None
    bad,_=decode_wire_containers({'operation':'search','query':'{"invented":1}'},RoutesInput.model_json_schema())
    with pytest.raises(ValueError):RoutesInput.model_validate(bad)
    malformed,_=decode_wire_containers({'operation':'search','query':'{broken'},RoutesInput.model_json_schema())
    with pytest.raises(ValueError):RoutesInput.model_validate(malformed)
    update={'operation':'update','holding_ref':'holding:existing','expected_revision':1,'valid_until':None,
            'authorization':json.dumps({'message_refs':['message:one'],'quotes':['clear expiry']}),'operation_key':'one'}
    decoded,_=decode_wire_containers(update,HoldingsWriteInput.model_json_schema())
    assert HoldingsWriteInput.model_validate(decoded).valid_until is None and 'valid_until' in decoded
    assert decode_wire_containers('{"literal":"text"}',{'anyOf':[{'type':'object'},{'type':'string'}]})==('{"literal":"text"}',[])
    assert decode_wire_containers('["a","b"]',{'type':'array','items':{'type':'string'}})==(['a','b'],[''])


@pytest.mark.parametrize('protocol',['native','json'])
def test_adapter_decodes_nested_containers_before_emitting_calls(protocol):
    from journeyplus.agent.harness.contracts import DTO,ToolDefinition
    class Nested(DTO):value:str
    class Input(DTO):payload:Nested|None=None
    raw={'payload':'{"value":"original"}'}
    async def scenario():
        def respond(request):
            if protocol=='native':
                return native_response([{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call',
                    'function':{'name':'example_read','arguments':json.dumps(raw)}}]},'finish_reason':'tool_calls'}]}])
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'finished':False,
                'calls':[{'id':'call','name':'example.read','arguments':raw}]})},'finish_reason':'stop'}]})
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(respond))
        model=AgentModel(AgentConfig('test','https://test/','',32768),client);model.protocol=protocol
        events=[e async for e in model.stream([],[ToolDefinition('example.read','Read',Input,None)],{},asyncio.Event())]
        call=next(e for e in events if e.type=='tool_call_ready')
        assert Input.model_validate(call.arguments).payload.value=='original'
        assert model.metrics[-1]['wire_decodings'][0]['paths']==['/payload']
        await client.aclose()
    asyncio.run(scenario())


def test_wire_result_omits_only_transport_bookkeeping_and_preserves_unknowns():
    from journeyplus.agent.adapters.model import wire_result
    from journeyplus.agent.harness.contracts import ToolResult
    original=ToolResult(data={'amount':None,'free':False,'unknowns':[], 'text':'原话'},
        coverage={'complete':False,'omissions':['unread']},artifact_refs=['artifact:full']).model_dump(mode='json')
    compact=wire_result(original)
    assert compact['data']==original['data']
    assert compact['coverage']==original['coverage']
    assert compact['artifact_refs']==['artifact:full']
    assert 'call_id' not in compact and 'metrics' not in compact and 'cache' not in compact


def test_provider_account_error_is_diagnostic_not_protocol_fallback():
    async def scenario():
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(400,json={'error':{'code':'Arrearage','message':'sensitive diagnostic body'}})
        client=httpx.AsyncClient(base_url='https://test/',transport=httpx.MockTransport(respond))
        model=AgentModel(AgentConfig('test','https://test/','',32768,protocol='auto'),client)
        with pytest.raises(RuntimeError):await model.initialize()
        assert len(requests)==1
        assert model.probe_diagnostics[0]['provider_code']=='Arrearage'
        assert model.metrics[0]['http_status']==400
        assert 'sensitive diagnostic body' not in json.dumps(model.metrics)
        await client.aclose()
    asyncio.run(scenario())


def test_inline_schema_keeps_business_properties_named_title():
    from journeyplus.agent.adapters.model import inline_schema
    from journeyplus.agent.tools.contracts import DisplayInput
    schema=inline_schema(DisplayInput.model_json_schema())
    block=schema['properties']['blocks']['items']
    assert 'title' in block['properties']
    assert 'title' not in block and 'title' not in block['properties']['title']
