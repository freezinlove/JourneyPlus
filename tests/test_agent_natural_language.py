"""Natural prose through the production assembly, using real original-schema tools.

These deterministic ModelPort drivers are regression tests, not provider evaluation.
"""
import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select

from journeyplus.agent.composition import compose_business
from journeyplus.agent.adapters.models import Artifact, RunCheckpoint
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
from journeyplus.agent.harness.contracts import ModelEvent, ModelMessage, Part
from tests.test_agent_original_runtime import migrated
from tests.test_agent_workflow_reads import original_factory, seed
from tests.test_harness_runtime import FakeModel, answer


def tool(name, arguments, call_id):
    return ModelEvent(type='tool_call_ready', name=name, arguments=arguments, call_id=call_id)


def last_result(messages):
    return next(p.result for m in reversed(messages) for p in m.content if p.type == 'tool_result')


def prose(view):
    return [p['text'] for m in view['messages'] if m['role'] == 'assistant'
            for p in m['content'] if p['type'] == 'text']


@pytest.mark.parametrize('show', [False, True])
def test_business_query_streams_prose_and_only_model_selected_graph(migrated, show):
    seed(migrated)
    progress = '我先查一下当前记录的匹配路线。'
    conclusion = '有匹配到 Gold 的路线，已记录的申请费是 49 美元，个人资格仍需核实。'

    class Model(FakeModel):
        async def stream(self, messages, definitions, limits, cancel_token):
            self.inputs.append(messages)
            assert 'response_format' not in limits
            assert not any('Final response JSON schema' in (p.text or '')
                           for m in messages for p in m.content)
            if len(self.inputs) == 1:
                yield ModelEvent(type='text_delta', text=progress)
                # Check while generation is still open: prose is already delivered
                # and reload can recover it without waiting for a final answer.
                events, status = store.events(workspace['id'], run['run_id'])
                assert status not in {'COMPLETED', 'PARTIAL', 'FAILED'}
                assert events[-1]['type'] == 'text_delta'
                assert prose(store.read(workspace['id'])) == [progress]
                yield tool('routes.evaluate', {'operation': 'search', 'query': {
                    'sources': {'mode': 'explicit', 'identities': [
                        {'program_name': 'Marriott Bonvoy', 'tier_name': 'Platinum'}]},
                    'target': {'program_name': 'Example Rewards'}}}, 'query')
                yield ModelEvent(type='turn_end', finish_reason='tool_calls')
            elif len(self.inputs) == 2 and show:
                result = last_result(messages)
                assert result['data']['candidates']
                yield ModelEvent(type='text_delta', text='我把查到的路线画出来。')
                yield tool('display.present', {'blocks': [{'type': 'route_graph',
                    'object_refs': result['data']['route_refs'][:1], 'title': '匹配路线'}]}, 'graph')
                yield ModelEvent(type='turn_end', finish_reason='tool_calls')
            else:
                if show:
                    assert last_result(messages)['data']['presentation_ref']
                else:
                    assert last_result(messages)['data']['candidates']
                for chunk in (conclusion[:12], conclusion[12:]):
                    yield ModelEvent(type='text_delta', text=chunk)
                yield ModelEvent(type='turn_end', finish_reason='stop')

    model = Model([])
    runtime, store = compose_business(migrated, model)
    workspace = store.create()
    run = store.start(workspace['id'], '我有万豪白金卡，看看有什么匹配路线。', 'query', 0)
    asyncio.run(runtime.run(run['run_id']))
    events, status = store.events(workspace['id'], run['run_id'])
    assert status == 'COMPLETED'
    assert len(model.inputs) == (3 if show else 2)
    text = ''.join(e['payload']['text'] for e in events if e['type'] == 'text_delta')
    assert text.startswith(progress) and text.endswith(conclusion)
    assert 'artifact:' not in text and 'deliveries' not in text
    view = store.read(workspace['id'])
    assert prose(view)[0] == progress and prose(view)[-1] == conclusion
    assert len(view['presentation_refs']) == int(show)
    assert sum(e['type'] == 'presentation.created' for e in events) == int(show)
    if show:
        attached = next(m for m in view['messages'] if m.get('attachments', {}).get('presentation_refs'))
        assert attached['content'][0]['text'] == '我把查到的路线画出来。'
        record = store.artifacts.read(workspace['id'], view['presentation_refs'][0])
        assert record['payload']['blocks'][0]['type'] == 'route_graph'
        assert record['payload']['blocks'][0]['payload']['objects']
    with migrated() as session:
        assert not list(session.scalars(select(Artifact).where(Artifact.kind == 'RESPONSE')))
        checkpoint = session.get(RunCheckpoint, UUID(run['run_id']))
        assert 'completion_failures' not in checkpoint.remaining_budget

    # Next turn keeps the plain response and original tool results in context;
    # it need not repeat a presentation or produce a delivery declaration.
    next_model = FakeModel([answer('好的，先保留这些信息。')])
    runtime.ports.model = next_model
    followup = store.start(workspace['id'], '先这样。', 'followup', view['revision'])
    asyncio.run(runtime.run(followup['run_id']))
    assert any(p.text == conclusion for m in next_model.inputs[0] for p in m.content)
    assert any(p.type == 'tool_result' for m in next_model.inputs[0] for p in m.content)
    assert store.read(workspace['id'])['presentation_refs'] == view['presentation_refs']


def test_authorized_write_and_delete_keep_real_receipts_without_final_envelope(migrated):
    prompt = '请保存测试俱乐部金卡，然后删除这条测试记录。'

    class Model(FakeModel):
        async def stream(self, messages, definitions, limits, cancel_token):
            self.inputs.append(messages)
            user = next(m for m in messages if m.role == 'user')
            if len(self.inputs) == 1:
                yield tool('holdings.write', {'operation': 'create', 'identity': {
                    'program_name': '测试俱乐部', 'tier_name': '金卡'},
                    }, 'create')
            elif len(self.inputs) == 2:
                saved = last_result(messages)
                assert saved['data']['outcome'] == 'APPLIED'
                row = saved['data']['entity']
                yield tool('holdings.write', {'operation': 'delete', 'holding_ref': row['ref'],
                    'expected_revision': row['revision'], }, 'delete')
            else:
                assert last_result(messages)['data']['outcome'] == 'APPLIED'
                yield ModelEvent(type='text_delta', text='测试记录已经保存并删除。')
            yield ModelEvent(type='turn_end', finish_reason='tool_calls' if len(self.inputs) < 3 else 'stop')

    runtime, store = compose_business(migrated, Model([]))
    workspace = store.create()
    run = store.start(workspace['id'], prompt, 'write', 0)
    asyncio.run(runtime.run(run['run_id']))
    events, status = store.events(workspace['id'], run['run_id'])
    assert status == 'COMPLETED'
    assert sum(e['type'] == 'operation.applied' for e in events) == 2
    view = store.read(workspace['id'])
    assert len(view['operations']) == 2
    assert prose(view) == ['测试记录已经保存并删除。']
    with migrated() as session:
        assert not list(session.scalars(select(WorkflowHolding)))


def test_failed_display_returns_to_model_for_natural_explanation(migrated):
    class Model(FakeModel):
        async def stream(self, messages, definitions, limits, cancel_token):
            self.inputs.append(messages)
            if len(self.inputs) == 1:
                yield tool('display.present', {'blocks': [{'type': 'route_graph',
                    'object_refs': ['artifact:00000000-0000-0000-0000-000000000000#route:missing']}]}, 'missing')
                yield ModelEvent(type='turn_end', finish_reason='tool_calls')
            else:
                assert last_result(messages)['error']
                yield ModelEvent(type='text_delta', text='这次没有成功生成路线图，原有资料仍保留。')
                yield ModelEvent(type='turn_end', finish_reason='stop')

    runtime, store = compose_business(migrated, Model([]))
    workspace = store.create()
    run = store.start(workspace['id'], '画出路线图。', 'display', 0)
    asyncio.run(runtime.run(run['run_id']))
    events, status = store.events(workspace['id'], run['run_id'])
    assert status == 'COMPLETED'  # A finished response, not proof of business success.
    assert not any(e['type'] == 'presentation.created' for e in events)
    assert not store.read(workspace['id'])['presentation_refs']
    assert prose(store.read(workspace['id'])) == ['这次没有成功生成路线图，原有资料仍保留。']


def test_business_cancel_preserves_streamed_natural_text(migrated):
    async def scenario():
        observed = asyncio.Event()

        class Model(FakeModel):
            async def stream(self, *args):
                yield ModelEvent(type='text_delta', text='我正在整理现有资料。')
                observed.set()
                await asyncio.Event().wait()

        runtime, store = compose_business(migrated, Model([]))
        workspace = store.create()
        run = store.start(workspace['id'], '帮我查一下。', 'cancel', 0)
        task = asyncio.create_task(runtime.run(run['run_id']))
        await asyncio.wait_for(observed.wait(), timeout=10)
        await runtime.cancel(run['run_id'])
        await task
        assert store.events(workspace['id'], run['run_id'])[1] == 'CANCELED'
        view = store.read(workspace['id'])
        assert prose(view) == ['我正在整理现有资料。']
        assert view['messages'][-1]['metadata']['interrupted'] is True

    asyncio.run(scenario())


def test_old_private_delivery_drafts_stay_hidden_on_reload_and_next_turn(migrated):
    model = FakeModel([answer('可以继续查看原来的资料。')])
    runtime, store = compose_business(migrated, model)
    workspace = store.create()
    run = store.start(workspace['id'], '之前的对话', 'old', 0)
    owner = '00000000-0000-0000-0000-000000000001'
    store.claim_run(run['run_id'], owner)
    for message in [
        ModelMessage(role='assistant', content=[Part(type='text', text='private-old-envelope')],
                     metadata={'completion_rejected': True}),
        ModelMessage(role='system', content=[Part(type='text', text='private-old-repair')],
                     metadata={'completion_feedback': True}),
        ModelMessage(role='assistant', content=[Part(type='text', text='原来已经显示的回答。')],
                     metadata={'completion_refs': ['artifact:historical-response']}),
    ]:
        store.append_message(run['run_id'], owner, message)
    store.finish_run(run['run_id'], owner, 'COMPLETED')
    view = store.read(workspace['id'])
    assert prose(view) == ['原来已经显示的回答。']
    new_run = store.start(workspace['id'], '继续。', 'new', view['revision'])
    asyncio.run(runtime.run(new_run['run_id']))
    visible_context = [p.text for m in model.inputs[0] for p in m.content if p.type == 'text']
    assert 'private-old-envelope' not in visible_context
    assert 'private-old-repair' not in visible_context
    assert '原来已经显示的回答。' in visible_context
