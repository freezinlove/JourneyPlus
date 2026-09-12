"""Server-recorded execution context and state-aware replay, not semantic approval."""
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from journeyplus.agent.adapters.artifacts import digest
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.models import now_utc
from journeyplus.workspace_models import WorkspaceMessage


def execution_snapshot(session, ctx):
    rows = list(session.scalars(select(WorkspaceMessage).where(
        WorkspaceMessage.workspace_id == UUID(ctx.workspace_id),
        WorkspaceMessage.turn_id == UUID(ctx.turn_id),
        WorkspaceMessage.role == 'USER').order_by(WorkspaceMessage.ordinal)))
    rows = [row for row in rows if not row.content.get('metadata', {}).get('legacy')]
    if not rows:
        raise PermissionError('A current user turn is required for this operation')
    return {
        'workspace_id': ctx.workspace_id, 'turn_id': ctx.turn_id, 'call_id': ctx.call_id,
        'scope': 'execution_context', 'semantic_authorization_verified': False,
        'messages': [{'id': str(row.id), 'created_at': row.created_at.isoformat()} for row in rows],
        'original_statements': [{'message_ref': str(row.id), 'text': '\n'.join(
            p.get('text') or '' for p in row.content.get('content', []) if p.get('type') == 'text')}
            for row in rows],
        'requested_at': now_utc().isoformat(),
    }


def receipt_result(row):
    return ToolResult(data={'operation_ref': 'operation:' + str(row.id), 'outcome': row.status,
        'before': deepcopy(row.before), 'after': deepcopy(row.after),
        'revision': (row.after or row.before or {}).get('revision')})


def prepare_operation(session, ctx, args, kind, current_state):
    """Called inside the existing write lock/transaction.

    Same-call recovery always returns its committed receipt. A different call
    can reuse an effect only within this turn and while its resulting entity
    state still holds. Record that NOOP under the new call for crash recovery.
    current_state returns {ref, revision}, or None for an absent entity.
    """
    snapshot = execution_snapshot(session, ctx)
    key = 'call:' + digest([ctx.workspace_id, ctx.turn_id, ctx.call_id])
    payload = args.model_dump(mode='json')
    # Update omission and explicit null have different business meanings.
    for field in ('identity', 'valid_until'):
        if field not in args.model_fields_set:
            payload.pop(field, None)
    hashed = digest([kind, payload])
    existing = session.scalar(select(OperationReceipt).where(
        OperationReceipt.owner_key == ctx.server_owner, OperationReceipt.idempotency_key == key))
    if existing:
        result = (receipt_result(existing) if existing.payload_hash == hashed and existing.operation_kind == kind
                  else ToolResult.failure('CONFLICT', 'The same call cannot change its operation or parameters'))
        return key, hashed, snapshot, result
    previous = session.scalar(select(OperationReceipt).where(
        OperationReceipt.owner_key == ctx.server_owner,
        OperationReceipt.operation_kind == kind, OperationReceipt.payload_hash == hashed,
        OperationReceipt.authorization_snapshot['workspace_id'].as_string() == ctx.workspace_id,
        OperationReceipt.authorization_snapshot['turn_id'].as_string() == ctx.turn_id,
    ).order_by(OperationReceipt.created_at.desc(), OperationReceipt.id.desc()).limit(1))
    if previous:
        after = previous.after
        expected = {'ref': after['ref'], 'revision': after['revision']} if after else None
        if current_state(previous.entity_id) == expected:
            replay = OperationReceipt(owner_key=ctx.server_owner, idempotency_key=key,
                operation_kind=kind, payload_hash=hashed, status='NOOP',
                entity_kind=previous.entity_kind, entity_id=previous.entity_id,
                before=deepcopy(after), after=deepcopy(after),
                authorization_snapshot={**snapshot, 'replayed_operation_ref': 'operation:' + str(previous.id)})
            session.add(replay)
            session.flush()
            return key, hashed, snapshot, receipt_result(replay)
    return key, hashed, snapshot, None
