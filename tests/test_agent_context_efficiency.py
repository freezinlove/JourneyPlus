"""Compact observations retain executable state and immutable detail access."""
import asyncio
import json
from dataclasses import replace

import pytest

from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import inline_schema, wire_messages
from journeyplus.agent.harness.context import project, ContextCapacityError
from journeyplus.agent.harness.contracts import Capabilities, ModelMessage, Part, ToolResult
from journeyplus.agent.tools.projection import model_view_for
from journeyplus.agent.tools.contracts import HoldingsWriteInput, WorkspaceReadInput, WaitingInput
from tests.test_agent_original_runtime import migrated, original_factory, setup


CAPS = Capabilities(native_tools=True, streaming=True, context_window=65536, max_output=4096)


def test_more_than_twelve_dialogue_messages_stay_until_token_pressure():
    messages = []
    for i in range(15):
        messages += [ModelMessage(role='user',content=[Part(type='text',text=f'条件 {i}')]),
                     ModelMessage(role='assistant',content=[Part(type='text',text='已记录')])]
    selected = project(messages, [], CAPS)
    assert [m.id for m in selected] == [m.id for m in messages]
    # A deliberately small target drops whole turns, with a usable history notice.
    small = project(messages, [], CAPS, context_token_budget=1000)
    assert len(small) < len(selected)
    assert small[-1].id == messages[-1].id
    assert any('history_available_before' in (p.text or '') for m in small for p in m.content)


def test_actual_input_estimator_drives_selection_and_hard_capacity():
    messages = [ModelMessage(role='user',content=[Part(type='text',text=str(i))]) for i in range(4)]
    def estimator(visible, definitions):
        return 1000 + 1000 * sum(m.role == 'user' for m in visible)
    selected = project(messages, [], CAPS, context_token_budget=3500, input_estimator=estimator)
    assert [m.id for m in selected if m.role == 'user'] == [m.id for m in messages[-2:]]
    with pytest.raises(ContextCapacityError):
        project(messages, [], CAPS, input_estimator=lambda *_: 100000)


def test_context_config_is_independent_of_provider_window(monkeypatch):
    monkeypatch.setenv('JOURNEYPLUS_AGENT_CONTEXT_WINDOW', '131072')
    monkeypatch.setenv('JOURNEYPLUS_AGENT_CONTEXT_TOKEN_BUDGET', '48000')
    config = AgentConfig.from_env()
    assert config.context_token_budget == 48000 and config.context_window == 131072
    with pytest.raises(ValueError):
        replace(config, context_token_budget=0)


def test_500k_budget_reaches_runtime_without_old_32k_clamp(session_factory):
    from journeyplus.agent.composition import compose_business
    from tests.test_harness_runtime import FakeModel
    config = AgentConfig('test', 'https://test/', '', context_window=1000000)
    assert config.context_token_budget == 500000
    model = FakeModel([])
    model.config = config
    runtime, _ = compose_business(session_factory, model, read_factory=session_factory)
    assert runtime.budget_limits == {'context_tokens':500000}
    messages = [ModelMessage(role='user', content=[Part(type='text',text='keep')])]
    capabilities = CAPS.model_copy(update={'context_window':config.context_window})
    selected = project(messages, [], capabilities, context_token_budget=config.context_token_budget,
        input_estimator=lambda *_: 200000)
    assert selected[-1].id == messages[-1].id


def test_operation_projection_retains_changes_unknowns_and_original_archive(migrated):
    runtime, store, ctx, _ = setup(migrated)
    memory = runtime.services['user_memory']
    created = memory.write(HoldingsWriteInput(operation='create',
        identity={'program_name':'测试俱乐部','tier_name':'金卡'}, valid_until='2030-01-01'),ctx)
    prior = created.data['after']
    updated = memory.write(HoldingsWriteInput(operation='update', holding_ref=prior['ref'],
        expected_revision=prior['revision'], valid_until=None), replace(ctx,call_id='update'))
    full = updated.model_dump(mode='json')
    ref = store.artifacts.put(ctx.workspace_id, 'TOOL_RESULT', full)
    updated.coverage['full_result_ref'] = ref
    view = model_view_for('holdings.write')(updated)
    assert view.data['entity']['valid_until'] is None
    assert view.data['entity']['identity_status'] == 'NEEDS_CONFIRMATION'
    assert view.data['entity']['ref'] == prior['ref']
    assert view.data['entity']['revision'] == updated.data['revision']
    assert view.data['changes'] == {'valid_until':{'from':'2030-01-01','to':None},
        'validity_status':{'from':'CURRENT','to':'NO_EXPIRY_RECORDED'}}
    assert 'source_record' not in view.data['entity'] and 'before' not in view.data
    assert len(view.model_dump_json().encode()) < len(updated.model_dump_json().encode()) * .7
    assert model_view_for('holdings.write')(view) == view
    # Normal workspace detail read still exposes the full original receipt.
    from journeyplus.agent.services.workspace import read
    detail = asyncio.run(read(WorkspaceReadInput(kind='artifact', refs=[ref]), ctx))
    assert 'source_record' in json.dumps(detail.data)
    assert store.artifacts.read(ctx.workspace_id,ref)['payload'] == full
    deleted = memory.write(HoldingsWriteInput(operation='delete',holding_ref=prior['ref'],
        expected_revision=updated.data['revision']),replace(ctx,call_id='delete'))
    assert model_view_for('holdings.write')(deleted).data['state']=='deleted'
    assert deleted.data['before']['source_record'] == updated.data['after']['source_record']
    repeated = memory.write(HoldingsWriteInput(operation='delete',holding_ref=prior['ref'],
        expected_revision=updated.data['revision']),replace(ctx,call_id='delete-again'))
    repeated_view = model_view_for('holdings.write')(repeated)
    assert repeated_view.data['outcome'] == 'NOOP'
    assert repeated_view.data['state'] == 'absent' and repeated_view.data['entity'] is None


def test_waiting_projection_keeps_conditions_readiness_and_cancel_status(migrated):
    runtime, _, ctx, _ = setup(migrated)
    service = runtime.services['waiting']
    args = WaitingInput(operation='create',query={'sources':{'mode':'none'},'constraints':{'max_amount':'100','currency':'EUR'}})
    created = service.manage(args, ctx)
    view = model_view_for('waiting.manage')(created)
    assert view.data['entity']['query'] == created.data['after']['query']
    assert view.data['entity']['readiness'] == created.data['after']['readiness']
    goal = view.data['entity']
    cancelled = service.manage(WaitingInput(operation='cancel',goal_ref=goal['ref'],
        expected_revision=goal['revision']), replace(ctx,call_id='cancel'))
    compact = model_view_for('waiting.manage')(cancelled)
    assert compact.data['entity']['status'] == 'CANCELLED'
    assert compact.data['changes']['status']['to'] == 'CANCELLED'
    failed = ToolResult.failure('CONFLICT','Changed; read again')
    assert model_view_for('waiting.manage')(failed) == failed
    partial = ToolResult(status='PARTIAL',data={'existing':goal},coverage={'complete':False,'omissions':['unread']})
    assert model_view_for('waiting.manage')(partial) == partial


def test_schema_compaction_preserves_nullable_primitives_and_constraints():
    schema = {'type':'object','properties':{
        'flag':{'anyOf':[{'type':'boolean'},{'type':'null'}],'default':None},
        'date':{'anyOf':[{'type':'string','pattern':'^x$'},{'type':'null'}],'default':None},
    },'additionalProperties':False}
    compact = inline_schema(schema)
    assert compact['properties']['flag']['type'] == ['boolean','null']
    assert compact['properties']['date']['anyOf'][0]['pattern'] == '^x$'
    assert 'default' not in compact['properties']['flag']
    assert schema['properties']['flag']['default'] is None


def test_native_pairing_and_focus_survive_metadata_compaction():
    user = ModelMessage(role='user',content=[Part(type='text',text='看这个')],
        metadata={'turn_id':'internal','focus_ref':'artifact:chosen','subject_refs':[]})
    tool = ModelMessage(role='tool',content=[Part(type='tool_result',call_id='call1',
        result=ToolResult(call_id='call1',coverage={'full_result_ref':'artifact:full','complete':False},
                          artifact_refs=['artifact:full']).model_dump(mode='json'))])
    wire = wire_messages([user,tool])
    assert 'artifact:chosen' in wire[0]['content'] and 'internal' not in wire[0]['content']
    assert wire[1]['tool_call_id']=='call1'
    result = json.loads(wire[1]['content'])
    assert 'call_id' not in result and 'artifact_refs' not in result
    assert result['coverage']=={'full_result_ref':'artifact:full','complete':False}
