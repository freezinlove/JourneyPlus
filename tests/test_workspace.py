from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.agent.workspace import WorkspaceService, WorkspaceError
from journeyplus.agent.workspace_contracts import MessageRequest, ConfirmRequest
from journeyplus.models import Base, StatusHolding
from journeyplus.knowledge.publication import CatalogService


@pytest.fixture
def factory():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def send(service, view, text='你好', key='first'):
    return service.message(UUID(view['id']), MessageRequest(text=text, client_message_id=key, expected_revision=view['revision']))


def known_workspace(service, changes):
    """Seed the object identities from a prior completed catalogue disclosure."""
    from journeyplus.models import AgentInteraction
    from journeyplus.knowledge.references import ReferenceMap
    from copy import deepcopy
    view=service.create()
    with service.factory.begin() as session:
        row=session.get(AgentInteraction,UUID(view['id']));state=deepcopy(row.state)
        ReferenceMap(state).encode(changes);row.state=state
    return service.read(UUID(view['id']))


def test_chat_has_no_business_reads_and_retry_is_idempotent(factory, monkeypatch):
    provider = SequenceAIProvider([{'action': 'ANSWER', 'payload': {'text': '你好，可以直接问我会籍问题。'}}])
    service = WorkspaceService(factory, provider)
    monkeypatch.setattr(service, '_tool', lambda *args: pytest.fail('chat read business data'))
    initial = service.create()
    result = send(service, initial)
    assert result['messages'][-1]['text'].startswith('你好')
    assert result['messages'][-1]['basis'] == []
    assert send(service, initial) == result
    assert len(provider.calls) == 1
    assert WorkspaceService(factory, provider).read(UUID(initial['id'])) == result


def test_invalid_action_repairs_once_without_forcing_target(factory):
    provider = SequenceAIProvider([{'action': 'garbage'}, {'action': 'ASK', 'payload': {'question': '你指的是哪一个活动？'}}])
    result = send(WorkspaceService(factory, provider), WorkspaceService(factory, provider).create(), '那个活动要多少钱')
    answer = result['messages'][-1]
    assert answer['repair_calls'] == 1 and answer['model_calls'] == 2
    assert 'error' not in answer


def test_two_bad_formats_are_recoverable_and_keep_input(factory):
    provider = SequenceAIProvider([{}, {}, {'action': 'ANSWER', 'payload': {'text': 'should not run'}}])
    service = WorkspaceService(factory, provider)
    result = send(service, service.create(), '随便聊聊')
    assert result['messages'][0]['text'] == '随便聊聊'
    assert result['messages'][-1]['error']['code'] == 'SCHEMA_ERROR'
    assert len(provider.calls) == 2


def test_unknown_action_is_distinct_from_missing_schema_fields(factory):
    provider=SequenceAIProvider([{'action':'EXECUTE','payload':{}},{'action':'EXECUTE','payload':{}}])
    service=WorkspaceService(factory,provider)
    result=send(service,service.create())
    assert result['messages'][-1]['error']['code']=='INVALID_ACTION'
    assert result['messages'][-1]['error']['run_ref']==result['messages'][-1]['turn_id']


def test_provider_connection_failure_is_not_unstructured_output(factory):
    import httpx
    class Offline:
        metadata=SequenceAIProvider([]).metadata
        def generate_structured(self,**kwargs):raise httpx.ConnectError('private connection detail')
    service=WorkspaceService(factory,Offline());result=send(service,service.create())
    answer=result['messages'][-1]
    assert answer['error']['code']=='PROVIDER_HTTP'
    assert 'private connection detail' not in str(answer)


def test_timeout_after_read_keeps_existing_activity_block(factory,monkeypatch):
    from uuid import uuid4
    class FailsAfterRead:
        metadata=SequenceAIProvider([]).metadata
        def __init__(self):self.calls=0
        def generate_structured(self,**kwargs):
            self.calls+=1
            if self.calls>1:raise TimeoutError()
            return kwargs['output_model'].model_validate({'action':'READ','payload':{'requests':[{'tool':'query_activity_materials','args':{'selector':{'text':'Example'}}}]}})
    service=WorkspaceService(factory,FailsAfterRead())
    activity={'ref':str(uuid4()),'version_ref':str(uuid4()),'title':'Verified activity'}
    def read(name,args,state,text):
        packet={'status':'OK','data':{'activities':[activity]}}
        state['activities']={activity['ref']:activity};state['materials']=[packet]
        return packet
    monkeypatch.setattr(service,'_tool',read)
    result=send(service,service.create());answer=result['messages'][-1]
    assert answer['error']['code']=='PROVIDER_TIMEOUT'
    assert answer['blocks'][0]['type']=='activity_card'
    assert answer['blocks'][0]['payload']['activities'][0]['title']=='Verified activity'
    assert WorkspaceService(factory,None).read(UUID(result['id']))==result


def test_third_read_renders_new_routes_without_a_fourth_model_call(factory,monkeypatch):
    from uuid import uuid4
    read={'action':'READ','payload':{'requests':[{'tool':'query_membership_routes','args':{}}]}}
    provider=SequenceAIProvider([read,read,read]);service=WorkspaceService(factory,provider)
    calls=[]
    def tool(name,args,state,text):
        calls.append(name)
        if len(calls)<3:return {'status':'NEEDS_INPUT','data':{}}
        r={'ref':str(uuid4()),'from':'A Gold','to':'B Silver','step_refs':[],'challenge':'UNKNOWN','material_caveats':[],
           'cost':{'state':'UNKNOWN','totals':[],'is_proven_free':False},'eligibility':'UNKNOWN'}
        state['routes'][r['ref']]=r;state['last_route_refs']=[r['ref']]
        return {'status':'PARTIAL','data':{'cards':[r]}}
    monkeypatch.setattr(service,'_tool',tool)
    result=send(service,service.create());answer=result['messages'][-1]
    assert len(provider.calls)==3
    assert answer['blocks'][0]['type']=='route_graph'
    assert answer['processing_note']=='MODEL_CALL_BUDGET_REACHED'


def test_disabled_research_returns_explicit_state(factory):
    provider = SequenceAIProvider([
        {'action': 'READ', 'payload': {'requests': [{'tool': 'research_statusmatcher', 'args': {'step_refs': ['K1'], 'question': '成功经验'}}]}},
        {'action': 'ANSWER', 'payload': {'text': '申请经验调查尚未启用。'}},
    ])
    service = WorkspaceService(factory, provider)
    result = send(service, service.create(), '调查申请经验')
    assert result['messages'][-1]['research_state'] == 'DISABLED'
    assert result['messages'][-1]['basis'][0]['status'] == 'DISABLED'


def test_holding_proposal_does_not_write_until_confirmation(factory):
    with factory.begin() as s:
        catalog = CatalogService(s)
        program = catalog.program('Example')
        tier = catalog.tier(program.id, 'Gold')
        changes = {'program_id': str(program.id), 'tier_id': str(tier.id)}
    provider = SequenceAIProvider([{'action': 'PROPOSE', 'payload': {'kind': 'HOLDING_SAVE', 'changes': changes, 'reason': '保存 Example Gold？'}}])
    service = WorkspaceService(factory, provider)
    result = send(service, known_workspace(service,changes), '保存我的 Example Gold')
    with factory() as s:
        assert s.scalar(select(StatusHolding)) is None
    request = ConfirmRequest(pending_action_id=result['pending_action']['id'], expected_revision=result['revision'], client_action_id='confirm-one', decision='CONFIRM')
    confirmed = service.confirm(UUID(result['id']), request)
    assert service.confirm(UUID(result['id']), request) == confirmed
    with factory() as s:
        assert len(list(s.scalars(select(StatusHolding)))) == 1
    assert len(provider.calls) == 1


def test_stale_message_does_not_call_provider(factory):
    provider = SequenceAIProvider([{'action': 'ANSWER', 'payload': {'text': '你好'}}])
    service = WorkspaceService(factory, provider)
    initial = service.create()
    send(service, initial)
    with pytest.raises(WorkspaceError, match='版本'):
        send(service, initial, key='another')
    assert len(provider.calls) == 1


def test_confirmation_rejects_changed_holdings(factory):
    with factory.begin() as s:
        catalog = CatalogService(s)
        program = catalog.program('Example')
        tier = catalog.tier(program.id, 'Gold')
        changes = {'program_id': str(program.id), 'tier_id': str(tier.id)}
    provider = SequenceAIProvider([{'action': 'PROPOSE', 'payload': {'kind': 'HOLDING_SAVE', 'changes': changes, 'reason': '保存会籍'}}])
    service = WorkspaceService(factory, provider)
    result = send(service, known_workspace(service,changes))
    with factory.begin() as s:
        s.add(StatusHolding(program_key='another', tier_key='gold', program_display_name='Another', tier_display_name='Gold'))
    with pytest.raises(WorkspaceError, match='会籍在确认前发生变化'):
        service.confirm(UUID(result['id']), ConfirmRequest(pending_action_id=result['pending_action']['id'], expected_revision=result['revision'], client_action_id='stale', decision='CONFIRM'))
    with factory() as s:
        assert len(list(s.scalars(select(StatusHolding)))) == 1


def test_workspace_http_preview_and_no_provider_recovery(factory):
    from fastapi.testclient import TestClient
    from journeyplus.product.api import create_product_app
    client = TestClient(create_product_app(factory))
    assert client.get('/workspace').status_code == 200
    assert client.get('/assets/workspace.js').status_code == 200
    created = client.post('/v2/agent/workspaces').json()
    response = client.post(f"/v2/agent/workspaces/{created['id']}/messages", json={'text': '你好', 'client_message_id': 'first', 'expected_revision': 0})
    assert response.status_code == 200
    assert response.json()['messages'][-1]['error']['code'] == 'CONFIG_UNAVAILABLE'


def test_workflow_model_runs_outside_database_transaction(factory):
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.workflow import KnowledgeWorkflow
    from journeyplus.knowledge.contracts import KnowledgeDraft
    from journeyplus.knowledge.models import Activity
    from sqlalchemy import event
    with factory.begin() as s:
        draft, _, _ = fixture_draft(s)
    workflow = KnowledgeWorkflow(factory, None)
    prepared = workflow.prepare(draft.activity_id, draft.documents)
    data = draft.model_dump(mode='json')
    data['extraction_key'] = prepared.extraction_key
    class Provider:
        def generate_structured(self, **kwargs):
            assert engine.pool.checkedout() == 0 if hasattr(engine.pool, 'checkedout') else not active
            return kwargs["output_model"].model_validate({"facts":data["facts"],"options":data["options"]})
    engine = factory.kw['bind']
    active = set()
    event.listen(engine, 'begin', lambda conn: active.add(id(conn)))
    event.listen(engine, 'commit', lambda conn: active.discard(id(conn)))
    event.listen(engine, 'rollback', lambda conn: active.discard(id(conn)))
    workflow.provider = Provider()
    result = workflow.publish(workflow.extract(prepared))
    assert result['status'] == 'PUBLISHED'
    with factory() as s:
        assert str(s.get(Activity, draft.activity_id).current_version_id) == result['version_id']


def test_workflow_rejects_model_changed_source_binding(factory):
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.workflow import KnowledgeWorkflow
    with factory.begin() as s:
        draft, _, _ = fixture_draft(s)
    provider = SequenceAIProvider([draft.model_dump(mode='json'),draft.model_dump(mode='json')])
    workflow = KnowledgeWorkflow(factory, provider)
    prepared = workflow.prepare(draft.activity_id, draft.documents)
    with pytest.raises(ValueError, match='Extra inputs'):
        workflow.extract(prepared)


def test_packet_budget_keeps_source_semantic_group_atomic():
    from journeyplus.knowledge.packets import decision_packet, encoded_bytes
    result = {'status':'OK','data': {'snippets': [{'ref': 'one', 'text': '表格' * 1000}, {'ref': 'two', 'text': '例外：不适用于匹配取得的会籍'}], 'facts': []}, 'coverage': {'search_complete': True}}
    packet = decision_packet(result, max_bytes=2000)
    assert packet['data']['snippets'] == []
    assert packet['coverage']['search_complete'] is True
    assert packet['coverage']['content_complete'] is False
    assert encoded_bytes(packet) <= 2000


def test_click_reads_exact_version_without_model_or_research(factory):
    from fastapi.testclient import TestClient
    from journeyplus.product.api import create_product_app
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.publication import PublicationService
    with factory.begin() as s:
        draft, _, _ = fixture_draft(s)
        version = PublicationService(s).publish(draft)
        version_id = str(version.id)
    class RouteProvider(SequenceAIProvider):
        def generate_structured(self, *, user_prompt, output_model, **kwargs):
            import json
            self.calls.append({})
            packets = json.loads(user_prompt)['tool_results']
            if not packets:
                response = {'action': 'READ', 'payload': {'requests': [{'tool': 'query_membership_routes', 'args': {'query': {'starting_tier_ids': [str(draft.options[0].source_scope.tier_ids[0])]}}}]}}
            else:
                response = {'action': 'ANSWER', 'payload': {'text': '查看方案', 'blocks': [{'type': 'route_graph', 'subject_refs': [packets[-1]['data']['cards'][0]['ref']]}]}}
            return output_model.model_validate(response)
    provider = RouteProvider([])
    client = TestClient(create_product_app(factory, ai_provider=provider))
    initial = known_workspace(WorkspaceService(factory,provider),{'tier_id':str(draft.options[0].source_scope.tier_ids[0])})
    base = f"/v2/agent/workspaces/{initial['id']}"
    result = client.post(base+'/messages', json={'text': '查路径', 'expected_revision': 0, 'client_message_id': 'first'}).json()
    answer = result['messages'][-1]
    ref = answer['blocks'][0]['subject_refs'][0]
    from journeyplus.models import AgentInteraction
    with factory.begin() as s:
        row=s.get(AgentInteraction,UUID(initial['id']));row.state={**row.state,'research':{'unrelated-cache':'must-not-be-returned'}}
    assert client.post(base+'/details',json={'ref':ref,'presentation_id':'wrong-message'}).status_code==404
    detail = client.post(base+'/details', json={'ref': ref,'presentation_id':answer['id']})
    assert detail.json()['research']==[]
    assert 'must-not-be-returned' not in detail.text
    assert detail.status_code == 200
    assert detail.json()['activities'][0]['version_ref'] == version_id
    assert client.post(base+'/focus', json={'ref': ref, 'presentation_id': answer['id'], 'expected_revision': result['revision']}).status_code == 200
    assert len(provider.calls) == 2


def test_expired_workspace_removes_temporary_messages(factory):
    from datetime import timedelta
    from journeyplus.models import AgentInteraction, now_utc
    from journeyplus.agent.workspace_models import WorkspaceMessage, WorkspaceTurn
    provider = SequenceAIProvider([{'action': 'ANSWER', 'payload': {'text': '你好'}}])
    service = WorkspaceService(factory, provider)
    result = send(service, service.create())
    with factory.begin() as s:
        s.get(AgentInteraction, UUID(result['id'])).expires_at = now_utc() - timedelta(seconds=1)
    with pytest.raises(WorkspaceError):
        service.read(UUID(result['id']))
    with factory() as s:
        assert s.scalar(select(WorkspaceMessage)) is None
        assert s.scalar(select(WorkspaceTurn)) is None


def test_activity_card_cannot_attach_fact_from_another_version(factory):
    from uuid import uuid4
    a,v,old=map(str,(uuid4(),uuid4(),uuid4()))
    state={'activities':{a:{'ref':a,'version_ref':v,'name':'Activity'}}}
    from journeyplus.knowledge.references import ReferenceMap
    refs=ReferenceMap(state)
    block={'type':'activity_card','subject_refs':[refs.encode(a)],'fact_refs':[refs.encode(old+'/facts/lifecycle')]}
    payload={'text':'活动详情','blocks':[block],'next_steps':[]}
    with pytest.raises(WorkspaceError,match='版本不一致'):
        WorkspaceService(factory,None)._assemble(payload,state,refs)


def test_final_format_failure_keeps_completed_route_answer(factory):
    from tests.test_knowledge_routes import edge
    with factory.begin() as s:root,target=edge(s)
    provider=SequenceAIProvider([
        {'action':'READ','payload':{'requests':[{'tool':'query_membership_routes','args':{'query':{'starting_tier_ids':[str(root)],'target_tier_id':str(target)}}}]}},
        {'action':'ANSWER','payload':{'text':'bad','fact_refs':[]}},
        {'action':'ANSWER','payload':{'text':'still bad','fact_refs':[]}},
    ])
    service=WorkspaceService(factory,provider)
    initial=known_workspace(service,{'starting_tier_ids':[str(root)],'target_tier_id':str(target)})
    result=send(service,initial,'请给我匹配路径')
    answer=result['messages'][-1]
    assert answer['processing_note']=='DETERMINISTIC_RESULT_AFTER_FORMAT_FAILURE'
    assert answer['diagnostic']['code']=='SCHEMA_ERROR'
    assert 'error' not in answer and answer['blocks'][0]['type']=='route_graph'
    assert '已确认费用' in answer['text'] and len(provider.calls)==3


def test_zero_routes_after_last_read_is_a_domain_result_not_budget_error(factory):
    read={'action':'READ','payload':{'requests':[{'tool':'query_membership_routes','args':{'query':{'starting_tier_ids':[],'use_saved_holdings':False}}}]}}
    service=WorkspaceService(factory,SequenceAIProvider([read,read,read]))
    answer=send(service,service.create(),'找无需已有会籍的申请机会')['messages'][-1]
    assert 'error' not in answer
    assert answer['processing_note']=='DETERMINISTIC_EMPTY_ROUTE_RESULT'
    assert '尚未找到可展示的已核实路径' in answer['text']


def test_unverified_source_list_is_not_official_absence(factory):
    from uuid import uuid4
    from journeyplus.knowledge.references import ReferenceMap
    identity,version=map(str,(uuid4(),uuid4()))
    state={'current_question':'具体接受哪些原有航空会籍？','current_activity_refs':[identity],
           'activities':{identity:{'ref':identity,'version_ref':version,'name':'Example','unresolved_aspects':['SOURCE_MAPPING']}}}
    refs=ReferenceMap(state);ref=refs.encode(identity)
    answer=WorkspaceService(factory,None)._assemble({'text':'官方未公开完整名单。','blocks':[{'type':'activity_card','subject_refs':[ref]}],'next_steps':[]},state,refs)
    assert '这不代表官方没有公布名单' in answer['text']
    assert '官方未公开完整名单' not in answer['text']


def test_all_unknown_source_mappings_use_formal_statement(factory):
    from uuid import uuid4
    from journeyplus.knowledge.references import ReferenceMap
    identity,version=map(str,(uuid4(),uuid4()))
    state={'current_question':'具体接受哪些原有航空会籍？','current_activity_refs':[identity],
           'activities':{identity:{'ref':identity,'version_ref':version,'name':'Example','unresolved_aspects':['SOURCE_MAPPING'],
                                   'source_mapping_counts':{'known':0,'unknown':3}}}}
    refs=ReferenceMap(state);ref=refs.encode(identity)
    answer=WorkspaceService(factory,None)._assemble({'text':'该活动页面没有公开披露名单。','blocks':[{'type':'activity_card','subject_refs':[ref]}],'next_steps':[]},state,refs)
    assert answer['presentation_policy']=='SERVER_SOURCE_MAPPING'
    assert '这不代表官方没有公布名单' in answer['text']


def test_evidence_answer_keeps_selected_earlier_material(factory):
    from uuid import uuid4
    from journeyplus.knowledge.references import ReferenceMap
    earlier,later=map(str,(uuid4(),uuid4()))
    first={'data':{'snippets':[{'ref':earlier,'text':'Earlier FAQ restriction'}]}}
    second={'data':{'snippets':[{'ref':later,'text':'Different activity terms'}]}}
    state={'materials':[first,second]};refs=ReferenceMap(state)
    refs.encode(second)
    payload={'text':'先前的限制如下','blocks':[{'type':'evidence_answer','subject_refs':[refs.encode(earlier)],'fact_refs':[]}],'next_steps':[]}
    answer=WorkspaceService(factory,None)._assemble(payload,state,refs)
    materials=answer['blocks'][0]['payload']['materials']
    assert len(materials)==1 and materials[0]['data']['snippets'][0]['text']=='Earlier FAQ restriction'


def test_exact_natural_confirmation_reuses_atomic_idempotent_gate(factory):
    with factory.begin() as s:
        catalog=CatalogService(s);program=catalog.program('Example');tier=catalog.tier(program.id,'Gold')
        changes={'program_id':str(program.id),'tier_id':str(tier.id)}
    provider=SequenceAIProvider([{'action':'PROPOSE','payload':{'kind':'HOLDING_SAVE','changes':changes,'reason':'请确认保存'}}])
    service=WorkspaceService(factory,provider);proposed=send(service,known_workspace(service,changes),'保存 Example Gold')
    confirmed=send(service,proposed,'确认',key='confirm-text')
    assert confirmed['messages'][-1]['text']=='会籍已保存。'
    assert confirmed['messages'][-1]['model_calls']==0 and len(provider.calls)==1
    assert send(service,proposed,'确认',key='confirm-text')==confirmed
    with factory() as s:assert len(list(s.scalars(select(StatusHolding))))==1


def test_cancel_save_with_topic_change_clears_pending_and_continues_chat(factory):
    with factory.begin() as s:
        catalog=CatalogService(s);program=catalog.program('Example');tier=catalog.tier(program.id,'Gold')
        changes={'program_id':str(program.id),'tier_id':str(tier.id)}
    provider=SequenceAIProvider([{'action':'PROPOSE','payload':{'kind':'HOLDING_SAVE','changes':changes,'reason':'请确认保存'}},
                                 {'action':'ANSWER','payload':{'text':'我们聊聊旅行。'}}])
    service=WorkspaceService(factory,provider);proposed=send(service,known_workspace(service,changes),'保存 Example Gold')
    result=send(service,proposed,'算了，先别保存，聊聊旅行。',key='change-topic')
    assert result['pending_action'] is None and '已取消' in result['messages'][-1]['text'] and '聊聊旅行' in result['messages'][-1]['text']
    assert send(service,proposed,'算了，先别保存，聊聊旅行。',key='change-topic')==result
    with factory() as s:assert s.scalar(select(StatusHolding)) is None


def test_ambiguous_acceptance_does_not_commit_holding(factory):
    with factory.begin() as s:
        catalog=CatalogService(s);program=catalog.program('Example');tier=catalog.tier(program.id,'Gold')
        changes={'program_id':str(program.id),'tier_id':str(tier.id)}
    provider=SequenceAIProvider([{'action':'PROPOSE','payload':{'kind':'HOLDING_SAVE','changes':changes,'reason':'请确认保存'}},
                                 {'action':'ASK','payload':{'question':'请确认是否保存？'}}])
    service=WorkspaceService(factory,provider);proposed=send(service,known_workspace(service,changes),'保存 Example Gold')
    send(service,proposed,'好吧，不过我还没决定有效期',key='ambiguous')
    with factory() as s:assert s.scalar(select(StatusHolding)) is None


def test_legacy_holding_edits_update_agent_identity_and_revision(factory, monkeypatch):
    from types import SimpleNamespace
    from journeyplus.product.holdings import StatusHoldingService
    from journeyplus.product.contracts import StatusHoldingInput
    from journeyplus.agent.workspace import holding_snapshot
    monkeypatch.setattr(StatusHoldingService, '_catalog_node', lambda self, program, tier:
        SimpleNamespace(program_key=program, tier_key=tier, program='Example-Air', tier=tier.title()))
    with factory.begin() as s:
        legacy = StatusHoldingService(s)
        saved = legacy.upsert(StatusHoldingInput(program_key='example air', tier_key='silver'))
        row = s.get(StatusHolding, saved.id)
        assert row.revision == 1 and row.tier_id is not None
        previous_tier = row.tier_id
        before = holding_snapshot(s)
        legacy.update(row.id, StatusHoldingInput(program_key='example air', tier_key='gold'))
        assert row.tier_id != previous_tier and row.revision == 2
        assert holding_snapshot(s) != before
        legacy.upsert(StatusHoldingInput(program_key='example air', tier_key='gold'))
        assert row.revision == 2
        changes = {'program_id': str(row.program_id), 'tier_id': str(previous_tier)}
        original_id = row.id
    provider = SequenceAIProvider([{'action': 'PROPOSE', 'payload': {
        'kind': 'HOLDING_SAVE', 'changes': changes, 'reason': '修改等级'}}])
    service = WorkspaceService(factory, provider)
    result = send(service, known_workspace(service,changes), '把我的 Example-Air 改成 Silver')
    service.confirm(UUID(result['id']), ConfirmRequest(
        pending_action_id=result['pending_action']['id'], expected_revision=result['revision'],
        client_action_id='bridge-confirm', decision='CONFIRM'))
    with factory() as s:
        rows = list(s.scalars(select(StatusHolding)))
        assert len(rows) == 1 and rows[0].id == original_id
        assert rows[0].tier_id == previous_tier and rows[0].revision == 3
        assert rows[0].program_key == 'example air'


def test_enabled_research_still_requires_user_intent_and_disclosed_steps(factory):
    from journeyplus.agent.step_research import StepResearchService
    import httpx
    def fail(request):pytest.fail('No network without both request and resolved step')
    researcher=StepResearchService(enabled=True,client=httpx.Client(transport=httpx.MockTransport(fail)))
    service=WorkspaceService(factory,None,researcher=researcher);state={}
    assert service._tool('research_statusmatcher',{'step_refs':['invented']},state,'你好')['status']=='NOT_REQUESTED'
    result=service._tool('research_statusmatcher',{'step_refs':['invented']},state,'调查申请经验')
    assert result['status']=='INSUFFICIENT' and result['http_requests']==0


def test_unresolved_activity_after_three_reads_asks_instead_of_crashing(factory):
    from journeyplus.knowledge.models import Activity
    with factory.begin() as s:
        program=CatalogService(s).program('Example Club')
        for edition in ['one','two']:
            s.add(Activity(identity_key=edition,primary_program_id=program.id,kind='STATUS_MATCH',edition_key=edition))
    read={'action':'READ','payload':{'requests':[{'tool':'query_activity_materials',
        'args':{'selector':{'text':'Example Club'},'question':'活动信息'}}]}}
    provider=SequenceAIProvider([read,read,read]);service=WorkspaceService(factory,provider)
    result=send(service,service.create(),'Example Club 有什么活动？')
    answer=result['messages'][-1]
    assert '哪一个活动' in answer['text'] and 'error' not in answer
    assert answer['blocks']==[] and len(provider.calls)==3


def test_bad_route_selection_can_recover_within_same_turn(factory):
    provider=SequenceAIProvider([
        {'action':'READ','payload':{'requests':[{'tool':'query_membership_routes','args':{'mode':'COMPARE','route_refs':['wrong']}}]}},
        {'action':'ASK','payload':{'question':'你想比较哪两条已展示的路径？'}}])
    service=WorkspaceService(factory,provider);result=send(service,service.create(),'比较路径')
    answer=result['messages'][-1]
    assert answer['model_calls']==2 and 'error' not in answer
    assert answer['basis'][0]['status']=='FAILED'
    assert 'INVALID_SELECTION' in provider.calls[1]['user_prompt']


def test_followup_context_distinguishes_activity_from_route():
    history=[{'id':'m1','blocks':[{'payload':{'activities':[{'ref':'K1','name':'Activity','version_ref':'K2'}]}}]},
             {'id':'m2','blocks':[{'payload':{'routes':[{'ref':'K3','from':'A','to':'B','step_refs':['K4']}]}}]}]
    result=WorkspaceService._recent_presentations(history)
    assert result[0]['objects'][0]['type']=='activity'
    assert result[1]['objects'][0]=={'type':'route','ref':'K3','from':'A','to':'B','step_refs':['K4'],'step_count':1,'position':1}


def test_two_clarifying_questions_do_not_turn_valid_natural_language_into_schema_failure(factory):
    provider=SequenceAIProvider([
        {'action':'ASK','payload':{'question':'你想接受付费吗？你有什么会籍？'}},
        {'action':'ASK','payload':{'question':'你指的是哪一个活动？'}}])
    service=WorkspaceService(factory,provider);result=send(service,service.create())
    answer=result['messages'][-1]
    assert answer['repair_calls']==0 and answer['text']=='你想接受付费吗？'
    assert len(provider.calls)==1 and answer['input_observations'][0]['presentation_adjustment']=='ONE_CLARIFICATION'


def test_complete_server_cache_is_projected_before_model_budgeting():
    from journeyplus.knowledge.packets import decision_packets
    packet={'status':'OK','server_routes':{'private':'X'*100000},'data':{'activities':[{'ref':'one','name':'Activity'}],'server_cache':'Y'*100000}}
    projected=decision_packets([packet],max_bytes=3000)[0]
    assert projected=={'status':'OK','data':{'activities':[{'ref':'one','name':'Activity'}]}}
    assert packet['data']['server_cache']  # The server object is not mutated.


def test_route_evaluation_preserves_explicit_adjustment_budget(factory):
    state={'routes':{},'steps':{}}
    service=WorkspaceService(factory,None)
    result=service._tool('query_membership_routes',{'mode':'EXPLORE','query':{}},state,
        '预算最多100美元，如果仅差预算，请给最小金额调整。')
    assert state['query']['max_amount']=='100' and state['query']['currency']=='USD'
    assert result['data']['query']['max_amount']=='100'


def test_guessed_database_identifier_is_rejected_before_tool_read(factory,monkeypatch):
    from uuid import uuid4
    provider=SequenceAIProvider([
        {'action':'READ','payload':{'requests':[{'tool':'query_activity_materials','args':{'selector':{'ref':str(uuid4())}}}]}},
        {'action':'ASK','payload':{'question':'你指哪个项目的活动？'}}])
    service=WorkspaceService(factory,provider)
    monkeypatch.setattr(service,'_tool',lambda *args:pytest.fail('Guessed identity touched the database tool'))
    answer=send(service,service.create())['messages'][-1]
    assert answer['model_calls']==2 and answer['basis'][0]['status']=='FAILED'
    assert 'error' not in answer


def test_explicit_disabled_research_is_visible_even_if_model_never_calls_tool(factory,monkeypatch):
    provider=SequenceAIProvider([{'action':'ANSWER','payload':{'text':'暂时没有经验信息。'}}])
    service=WorkspaceService(factory,provider)
    monkeypatch.setattr(service,'_tool',lambda *args:pytest.fail('Disabled-only question read a business tool'))
    answer=send(service,service.create(),'请查 StatusMatcher 的匹配经验。')['messages'][-1]
    assert answer['research_state']=='DISABLED' and '未读取经验报告' in answer['text']
    assert answer['basis']==[{'tool':'research_statusmatcher','status':'DISABLED','reason':'CAPABILITY_CHECK','coverage':{'http_requests':0}}]
    assert answer['model_calls']==1


def test_successful_repair_is_not_replayed_on_next_business_decision(factory,monkeypatch):
    import json
    provider=SequenceAIProvider([{}, {'action':'READ','payload':{'requests':[{'tool':'query_activity_materials','args':{'selector':{'text':'Example'}}}]}}, {'action':'ANSWER','payload':{'text':'当前资料不足。'}}])
    service=WorkspaceService(factory,provider)
    monkeypatch.setattr(service,'_tool',lambda *args:{'status':'NOT_FOUND','data':{}})
    answer=send(service,service.create(),'Example 的条件是什么')['messages'][-1]
    assert answer['model_calls']==3 and answer['repair_calls']==1 and not answer.get('error')
    assert 'format_repair' in json.loads(provider.calls[1]['user_prompt'])
    assert 'format_repair' not in json.loads(provider.calls[2]['user_prompt'])


def test_public_opportunity_search_does_not_require_optional_target_preference(factory):
    read={'action':'READ','payload':{'requests':[{'tool':'query_membership_routes',
        'args':{'mode':'EXPLORE','query':{'use_saved_holdings':False,'starting_tier_ids':[]}}}]}}
    provider=SequenceAIProvider([
        {'action':'ASK','payload':{'question':'您有偏好的目标项目或联盟吗？'}},read,read])
    answer=send(WorkspaceService(factory,provider),WorkspaceService(factory,provider).create(),
        '假设我没有任何已有会籍，请找不需要已有会籍就能申请的匹配或挑战机会。')['messages'][-1]
    assert not answer.get('error')
    assert any(row['tool']=='query_membership_routes' for row in answer['basis'])
    assert '未找到' in answer['text'] or '未核实路径' in answer['text'] or '尚未找到' in answer['text']
