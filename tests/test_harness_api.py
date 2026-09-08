from fastapi.testclient import TestClient
from journeyplus.agent.composition import compose_business
from journeyplus.product.agent_api import create_agent_app
from tests.test_harness_runtime import FakeModel,answer


def test_independent_api_runs_streams_and_conflicts(session_factory):
    runtime,store=compose_business(session_factory,FakeModel([answer('Hello from v3')]))
    with TestClient(create_agent_app(runtime,store,initialize_model=False)) as client:
        w=client.post('/v3/agent/workspaces',json={}).json();base='/v3/agent/workspaces/'+w['id']
        request={'text':'hello','client_message_id':'one','expected_revision':0}
        response=client.post(base+'/runs',json=request);assert response.status_code==202
        run=response.json()['run_id']
        events=client.get(base+'/runs/'+run+'/events').text
        assert 'text_delta' in events and 'Hello from v3' in events and 'completed' in events
        assert client.post(base+'/runs',json=request).json()['run_id']==run
        assert client.post(base+'/runs',json={**request,'text':'changed'}).status_code==409
        assert client.get('/workspace').status_code==200
        assert client.get(base).json()['messages'][-1]['content'][0]['text']=='Hello from v3'


def test_presentation_paging_scope_order_and_render_failure_context(session_factory):
    runtime,store=compose_business(session_factory,FakeModel([]));w=store.create();other=store.create()
    objects=[{'ref':f'object:{number}','data':{'title':str(number)}} for number in reversed(range(12))]
    ref=store.artifacts.put(w['id'],'PRESENTATION',{'blocks':[{'id':'selected','payload':{'objects':objects}}]})
    base='/v3/agent/workspaces/'+w['id']
    with TestClient(create_agent_app(runtime,store,initialize_model=False)) as client:
        endpoint=base+'/presentations/'+ref.removeprefix('artifact:')
        first=client.post(endpoint+'/browse',json={'cursor':ref+'|0|0','expected_revision':0})
        assert first.status_code==200 and first.json()['ordered_refs']==[item['ref'] for item in objects[:8]]
        last=client.post(endpoint+'/browse',json={'cursor':first.json()['next_cursor'],'expected_revision':0})
        assert last.json()['ordered_refs']==[item['ref'] for item in objects[8:]] and last.json()['next_cursor'] is None
        assert client.post(endpoint+'/browse',json={'cursor':ref+'|0|0','expected_revision':9}).status_code==409
        cross=endpoint.replace(w['id'],other['id'])
        assert client.post(cross+'/browse',json={'cursor':ref+'|0|0','expected_revision':0}).status_code==404
        feedback={'event_id':'render-one','status':'FAILED','error_code':'CANVAS_UNAVAILABLE'}
        assert client.post(endpoint+'/feedback',json=feedback).status_code==200
        assert client.post(endpoint+'/feedback',json=feedback).status_code==200
        assert client.post(endpoint+'/feedback',json={**feedback,'status':'RENDERED'}).status_code==409
        context=store.load_context_index(w['id'])
        assert 'CANVAS_UNAVAILABLE' in context['messages'][-1].content[0].text
        assert store.read(w['id'])['revision']==0
        assert runtime.ports.model.inputs==[]


def test_presentation_receipt_stays_attached_to_its_original_message(session_factory):
    import asyncio
    from journeyplus.agent.harness.contracts import ModelEvent
    from journeyplus.knowledge.models import Activity
    from tests.test_knowledge_routes import edge
    from sqlalchemy import select
    with session_factory.begin() as session:edge(session)
    with session_factory() as session:
        activity=session.scalar(select(Activity));ref='activity:'+str(activity.id)+'@'+str(activity.current_version_id)
    call=ModelEvent(type='tool_call_ready',call_id='selected-card',name='display.present',arguments={
        'blocks':[{'type':'activity_card','object_refs':[ref]}]})
    model=FakeModel([[call.model_dump(),{'type':'turn_end','finish_reason':'tool_calls'}],answer('Here is the card.'),answer('A later answer.')])
    runtime,store=compose_business(session_factory,model);w=store.create()
    first=store.start(w['id'],'show card','one',0);asyncio.run(runtime.run(first['run_id']))
    second=store.start(w['id'],'follow up','two',store.read(w['id'])['revision']);asyncio.run(runtime.run(second['run_id']))
    view=store.read(w['id']);messages=view['messages']
    attached=[m for m in messages if m.get('attachments',{}).get('presentation_refs')]
    assert len(attached)==1, store.load_context_index(w['id'])
    assert attached[0]['attachments']['presentation_refs']==view['presentation_refs']
    assert messages.index(attached[0])<next(i for i,m in enumerate(messages) if any(p.get('text')=='follow up' for p in m['content']))
