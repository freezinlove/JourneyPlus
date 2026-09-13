"""Business effects keep reliable replay with only model-selected business inputs."""
import asyncio
from dataclasses import replace
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from tests.test_agent_original_runtime import migrated, setup, original_factory
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
from journeyplus.agent.services.workspace import note
from journeyplus.agent.tools.contracts import (
    INPUTS, HoldingsReadInput, HoldingsWriteInput, WaitingInput, NoteInput,
)


def call_context(ctx, name):
    return replace(ctx, call_id=name)


def create_args():
    return HoldingsWriteInput(operation='create', identity={'program_name': '测试俱乐部', 'tier_name': '金卡'})


def test_model_schemas_have_no_proof_or_operation_key_fields():
    removed = {'authorization', 'operation_key', 'constraint_changes', 'source_message_refs'}
    for name, model in INPUTS.items():
        assert not removed & set(model.model_fields), name
    assert 'research.parse' not in INPUTS
    with pytest.raises(ValueError):
        HoldingsWriteInput.model_validate({**create_args().model_dump(), 'authorization': {}})


def test_new_call_replay_records_its_own_receipt_and_same_call_recovers(migrated):
    runtime, store, ctx, _ = setup(migrated)
    memory = runtime.services['user_memory']
    args = create_args()
    first = memory.write(args, call_context(ctx, 'create'))
    assert memory.write(args, call_context(ctx, 'create')).data == first.data
    second = memory.write(args, call_context(ctx, 'duplicate'))
    assert second.data['outcome'] == 'NOOP'
    assert second.data['after'] == first.data['after']
    assert second.data['operation_ref'] != first.data['operation_ref']
    recovered = store.committed_call_result(ctx.workspace_id, ctx.turn_id, 'duplicate')
    assert recovered.data == second.data
    with migrated() as session:
        records = list(session.scalars(select(OperationReceipt)))
        assert len(records) == 2
        assert all(r.authorization_snapshot['semantic_authorization_verified'] is False for r in records)
        assert not any('quotes' in r.authorization_snapshot for r in records)
        assert len(list(session.scalars(select(WorkflowHolding)))) == 1


def test_external_edit_prevents_cross_call_replay_and_stale_update(migrated):
    runtime, _, ctx, _ = setup(migrated)
    memory = runtime.services['user_memory']
    args = create_args()
    created = memory.write(args, call_context(ctx, 'create')).data['after']
    with migrated.begin() as session:
        session.get(WorkflowHolding, UUID(created['ref'][8:])).valid_until = date(2030, 1, 1)
    assert memory.write(args, call_context(ctx, 'create-again')).error.code == 'CONFLICT'
    stale = HoldingsWriteInput(operation='delete', holding_ref=created['ref'], expected_revision=created['revision'])
    assert memory.write(stale, call_context(ctx, 'stale')).error.code == 'CONFLICT'
    assert memory.read(HoldingsReadInput())[0]['valid_until'] == '2030-01-01'


def test_create_delete_recreate_and_repeated_update_delete(migrated):
    runtime, _, ctx, _ = setup(migrated)
    memory = runtime.services['user_memory']
    args = create_args()
    created = memory.write(args, call_context(ctx, 'create')).data['after']
    update = HoldingsWriteInput(operation='update', holding_ref=created['ref'],
        expected_revision=created['revision'], valid_until='2030-01-01')
    updated = memory.write(update, call_context(ctx, 'update'))
    assert updated.data['outcome'] == 'APPLIED'
    assert memory.write(update, call_context(ctx, 'update-again')).data['outcome'] == 'NOOP'
    delete = HoldingsWriteInput(operation='delete', holding_ref=created['ref'],
        expected_revision=updated.data['revision'])
    assert memory.write(delete, call_context(ctx, 'delete')).data['outcome'] == 'APPLIED'
    assert memory.write(delete, call_context(ctx, 'delete-again')).data['outcome'] == 'NOOP'
    assert memory.read(HoldingsReadInput()) == []
    recreated = memory.write(args, call_context(ctx, 'recreate'))
    assert recreated.data['outcome'] == 'APPLIED'
    assert recreated.data['after']['ref'] != created['ref']


def test_same_call_changed_arguments_conflict_and_new_turn_is_new_operation(migrated):
    runtime, store, ctx, _ = setup(migrated)
    memory = runtime.services['user_memory']
    args = create_args()
    first = memory.write(args, ctx)
    changed = HoldingsWriteInput(operation='create', identity=args.identity, valid_until='2030-01-01')
    assert memory.write(changed, ctx).error.code == 'CONFLICT'
    from journeyplus.agent.adapters.models import RunCheckpoint
    with migrated() as session:
        run = session.scalar(select(RunCheckpoint).where(RunCheckpoint.turn_id == UUID(ctx.turn_id)))
        run_id = str(run.run_id)
    owner = str(uuid4())
    store.claim_run(run_id, owner)
    store.finish_run(run_id, owner, 'COMPLETED')
    store.start(ctx.workspace_id, '再次保存同一条会籍', 'second', store.read(ctx.workspace_id)['revision'])
    new_turn = store.load_context_index(ctx.workspace_id)['messages'][-1].metadata['turn_id']
    second = memory.write(args, replace(ctx, turn_id=new_turn))
    assert second.data['outcome'] == 'NOOP'
    assert second.data['operation_ref'] != first.data['operation_ref']
    with migrated() as session:
        receipt = session.get(OperationReceipt, UUID(second.data['operation_ref'][10:]))
        assert 'replayed_operation_ref' not in receipt.authorization_snapshot
        assert receipt.authorization_snapshot['turn_id'] == new_turn


def test_waiting_repeated_create_update_cancel_and_new_goal(migrated):
    runtime, store, ctx, _ = setup(migrated)
    service = runtime.services['waiting']
    args = WaitingInput(operation='create', query={'sources': {'mode': 'none'}})
    first = service.manage(args, call_context(ctx, 'create'))
    goal = first.data['after']
    assert service.manage(args, call_context(ctx, 'again')).data['outcome'] == 'NOOP'
    update = WaitingInput(operation='update', goal_ref=goal['ref'], expected_revision=goal['revision'],
        query={'sources': {'mode': 'none'}, 'constraints': {'free_only': True}})
    updated = service.manage(update, call_context(ctx, 'update'))
    assert service.manage(update, call_context(ctx, 'update-again')).data['outcome'] == 'NOOP'
    cancel = WaitingInput(operation='cancel', goal_ref=goal['ref'], expected_revision=updated.data['revision'])
    assert service.manage(cancel, call_context(ctx, 'cancel')).data['outcome'] == 'APPLIED'
    assert service.manage(cancel, call_context(ctx, 'cancel-again')).data['outcome'] == 'NOOP'
    new = service.manage(args, call_context(ctx, 'new'))
    assert new.data['outcome'] == 'APPLIED'
    assert new.data['after']['ref'] != goal['ref']


def test_note_automatically_records_current_turn_without_model_references(migrated):
    _, store, ctx, _ = setup(migrated)
    result = asyncio.run(note(NoteInput(expected_revision=0, content='本轮在比较两种方案。'), ctx))
    assert result.error is None
    saved = store.artifacts.read(ctx.workspace_id, result.data['note_ref'])['payload']
    assert saved['source_message_refs'] == store.user_message_refs(ctx.workspace_id, ctx.turn_id)
    assert saved['revision'] == 1
    conflict = asyncio.run(note(NoteInput(expected_revision=0, content='旧版本覆盖'), call_context(ctx, 'stale-note')))
    assert conflict.error.code == 'CONFLICT'


@pytest.mark.parametrize('duplicate', [False, True])
def test_runtime_recovers_commit_before_tool_result_without_second_effect(migrated, duplicate):
    from datetime import timedelta
    from journeyplus.agent.adapters.models import RunCheckpoint
    from journeyplus.agent.composition import compose_business
    from journeyplus.agent.harness.contracts import ModelMessage, Part
    from journeyplus.models import now_utc
    from tests.test_harness_runtime import FakeModel, answer
    runtime, store, ctx, _ = setup(migrated)
    with migrated() as session:
        run_id = str(session.scalar(select(RunCheckpoint).where(
            RunCheckpoint.turn_id == UUID(ctx.turn_id))).run_id)
    owner = str(uuid4())
    store.claim_run(run_id, owner)
    args = create_args()
    if duplicate:
        assert runtime.services['user_memory'].write(args, call_context(ctx, 'first')).data['outcome'] == 'APPLIED'
    call = {'call_id': 'interrupted', 'name': 'holdings.write',
            'arguments': args.model_dump(mode='json', exclude_unset=True)}
    store.append_message(run_id, owner, ModelMessage(role='assistant', content=[Part(type='tool_call', **call)]))
    call['tool_version'] = runtime.ports.registry.validate(call['name'], call['arguments'])[0][0].version
    store.save_checkpoint(run_id, owner, phase='TOOLS_PENDING', pending_calls=[call])
    store.tool_intent(run_id, owner, call, 'USER_WRITE')
    committed = runtime.services['user_memory'].write(args, call_context(ctx, 'interrupted'))
    assert committed.data['outcome'] == ('NOOP' if duplicate else 'APPLIED')
    with migrated.begin() as session:
        session.get(RunCheckpoint, UUID(run_id)).heartbeat_at = now_utc() - timedelta(seconds=46)
    model = FakeModel([answer('操作结果已恢复。')])
    recovered, new_store = compose_business(migrated, model)
    asyncio.run(recovered.run(run_id))
    assert new_store.events(ctx.workspace_id, run_id)[1] == 'COMPLETED'
    results = [part.result for msg in model.inputs[0] for part in msg.content if part.type == 'tool_result']
    assert len(results) == 1 and results[0]['data']['operation_ref'] == committed.data['operation_ref']
    with migrated() as session:
        assert len(list(session.scalars(select(WorkflowHolding)))) == 1
        assert len(list(session.scalars(select(OperationReceipt)))) == (2 if duplicate else 1)
