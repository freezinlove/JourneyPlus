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
    result = send(service, service.create(), '保存我的 Example Gold')
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
    result = send(service, service.create())
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
            return KnowledgeDraft.model_validate(data)
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
    provider = SequenceAIProvider([draft.model_dump(mode='json')])
    workflow = KnowledgeWorkflow(factory, provider)
    prepared = workflow.prepare(draft.activity_id, draft.documents)
    with pytest.raises(ValueError, match='改变了服务端绑定'):
        workflow.extract(prepared)


def test_packet_budget_keeps_source_semantic_group_atomic():
    from journeyplus.knowledge.packets import decision_packet, encoded_bytes
    result = {'data': {'snippets': [{'ref': 'one', 'text': '表格' * 1000}, {'ref': 'two', 'text': '例外：不适用于匹配取得的会籍'}], 'facts': []}, 'coverage': {'search_complete': True}}
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
    initial = client.post('/v2/agent/workspaces').json()
    base = f"/v2/agent/workspaces/{initial['id']}"
    result = client.post(base+'/messages', json={'text': '查路径', 'expected_revision': 0, 'client_message_id': 'first'}).json()
    answer = result['messages'][-1]
    ref = answer['blocks'][0]['subject_refs'][0]
    detail = client.post(base+'/details', json={'ref': ref})
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
