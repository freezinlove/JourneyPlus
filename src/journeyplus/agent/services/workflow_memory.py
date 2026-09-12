"""Keep user authorization and receipts while writing the original holding model."""
from datetime import date
from uuid import UUID
from sqlalchemy import select, text
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding as Holding, holding_revision
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.adapters.artifacts import digest
from journeyplus.agent.adapters.transactions import read_session, transaction
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.membership.normalization import normalize_key, normalize_tier
from journeyplus.models import now_utc
from .identities import canonical
from .user_memory import UserMemory, receipt_result


class WorkflowUserMemory(UserMemory):
    business_journal = False  # Unified-model replay is retired; durable receipts remain.

    def view(self, session, row, *, resolved=None, source_record=None):
        if row is None:
            return None
        revision = holding_revision(row)
        if source_record is None:
            receipt = session.scalar(select(OperationReceipt).where(
                OperationReceipt.entity_kind == 'HOLDING', OperationReceipt.entity_id == row.id
            ).order_by(OperationReceipt.created_at.desc(), OperationReceipt.id.desc()).limit(1))
            after = receipt.after if receipt else None
            source_record = after.get('source_record', {}) if after and after.get('revision') == revision else {}
        if resolved is None:
            with self.knowledge.read() as knowledge_session:
                resolved = self.identities.resolve(knowledge_session,
                    {'program_name': row.program_display_name, 'tier_name': row.tier_display_name}, require_tier=True)
        bound = resolved.get('status') == 'OK'
        return {'ref': 'holding:' + str(row.id), 'revision': revision,
                'program_name': row.program_display_name, 'tier_name': row.tier_display_name,
                'program_ref': resolved.get('program_ref') if bound else None,
                'tier_ref': resolved.get('tier_ref') if bound else None,
                'valid_until': row.valid_until.isoformat() if row.valid_until else None,
                'identity_status': 'CONFIRMED' if bound else 'NEEDS_CONFIRMATION',
                'name_authority': 'CATALOG' if bound else 'UNVERIFIED_EXTRACTION',
                'source_record': source_record,
                'display_statement': '\n'.join(x['text'] for x in source_record.get('original_statements', [])) or None}

    def read(self, args):
        with read_session(self.factory) as session:
            statement = select(Holding).order_by(Holding.created_at, Holding.id)
            if not args.include_expired:
                statement = statement.where((Holding.valid_until.is_(None)) | (Holding.valid_until >= now_utc().date()))
            if args.holding_refs:
                statement = statement.where(Holding.id.in_([UUID(r.removeprefix('holding:')) for r in args.holding_refs]))
            values = [self.view(session, row) for row in session.scalars(statement)]
            if args.query:
                values = [v for v in values if canonical(args.query) in canonical(
                    v['program_name'] + ' ' + v['tier_name'] + ' ' + (v['display_statement'] or ''))]
            return values

    def write(self, args, ctx):
        # Resolve catalog references before taking the user-data write lock.
        resolved = identity = None
        if args.identity:
            with self.knowledge.read() as session:
                resolved = self.identities.resolve(session, args.identity, require_tier=True, context=ctx)
            if resolved['status'] == 'OK':
                program, tier = resolved['program_name'], resolved['tier_name']
            elif hasattr(args.identity, 'program_name') and args.identity.tier_name:
                program, tier = args.identity.program_name, args.identity.tier_name
            else:
                return ToolResult.failure('INVALID_ARGUMENT', 'A program and tier name or uniquely bound tier is required')
            identity = dict(program_key=normalize_key(program), tier_key=normalize_tier(tier),
                            program_display_name=program, tier_display_name=tier)
        try:
            with transaction(self.factory) as session:
                if session.info.get('user_business_writes_paused'):
                    return ToolResult.failure('USER_WRITES_PAUSED', 'User writes are paused')
                if session.bind.dialect.name == 'postgresql':
                    session.execute(text('SELECT pg_advisory_xact_lock(748293001)'))
                authorization = self.authorize(session, ctx, args.authorization)
                key = ctx.workspace_id + ':' + args.authorization.message_refs[-1] + ':' + args.operation_key
                hashed = digest(args.model_dump(mode='json', exclude_unset=True))
                receipt = session.scalar(select(OperationReceipt).where(
                    OperationReceipt.owner_key == ctx.server_owner, OperationReceipt.idempotency_key == key))
                if receipt:
                    return receipt_result(receipt) if receipt.payload_hash == hashed else ToolResult.failure('CONFLICT', 'Operation key payload changed')
                row = session.get(Holding, UUID(args.holding_ref.removeprefix('holding:')), with_for_update=True) if args.holding_ref else None
                if args.operation != 'create' and (row is None or holding_revision(row) != args.expected_revision):
                    return ToolResult.failure('CONFLICT', 'Holding changed or is missing; read it again')
                if identity:
                    collision = session.scalar(select(Holding).where(Holding.program_key == identity['program_key']).with_for_update())
                    if collision and (row is None or collision.id != row.id):
                        if args.operation != 'create' or collision.tier_key != identity['tier_key'] or collision.valid_until != (date.fromisoformat(args.valid_until) if args.valid_until else None):
                            return ToolResult.failure('CONFLICT', 'Program already has a different holding; explicit update required')
                        row = collision
                before = self.view(session, row)
                source = {'original_statements': authorization['original_statements'],
                          'extracted_identity': args.identity.model_dump(mode='json') if args.identity else None,
                          'interpretation_verified': False}
                if not identity and before:
                    source = before.get('source_record', {})
                outcome = 'APPLIED'
                if args.operation == 'create':
                    if row:
                        outcome = 'NOOP'
                    else:
                        row = Holding(**identity, valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None)
                        session.add(row)
                elif args.operation == 'update':
                    if identity:
                        for name, value in identity.items():
                            setattr(row, name, value)
                    if 'valid_until' in args.model_fields_set:
                        row.valid_until = date.fromisoformat(args.valid_until) if args.valid_until else None
                    if not session.is_modified(row):
                        outcome = 'NOOP'
                else:
                    session.delete(row)
                session.flush()
                after = None if args.operation == 'delete' else (before if outcome == 'NOOP' else self.view(
                    session, row, resolved=resolved, source_record=source))
                receipt = OperationReceipt(owner_key=ctx.server_owner, idempotency_key=key,
                    operation_kind='holding.' + args.operation, payload_hash=hashed, status=outcome,
                    entity_kind='HOLDING', entity_id=row.id, before=before, after=after, authorization_snapshot=authorization)
                session.add(receipt)
                session.flush()
                return receipt_result(receipt)
        except PermissionError as exc:
            return ToolResult.failure('NOT_AUTHORIZED', str(exc))
