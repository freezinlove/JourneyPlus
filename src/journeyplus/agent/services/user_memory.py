"""Atomic user-authorized effects, journal entries and durable idempotency receipts."""
from journeyplus.agent.adapters.transactions import read_session
from datetime import date
from uuid import UUID
from sqlalchemy import select, text
from journeyplus.models import StatusHolding, now_utc
from journeyplus.knowledge import user_journal as _journal  # registers transaction listeners
from journeyplus.workspace_models import WorkspaceMessage
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.adapters.artifacts import digest
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.membership.normalization import normalize_key, normalize_tier
from .identities import canonical


def holding_view(row):
    if row is None:return None
    source=row.source_record or {}
    return {'ref':'holding:'+str(row.id),'revision':row.revision,'program_name':row.program_display_name,
            'tier_name':row.tier_display_name,'program_ref':'program:'+str(row.program_id) if row.program_id else None,
            'tier_ref':'tier:'+str(row.tier_id) if row.tier_id else None,'valid_until':row.valid_until.isoformat() if row.valid_until else None,
            'identity_status':row.identity_status,'source_record':source,
            'name_authority':'CATALOG' if row.program_id and row.tier_id else 'UNVERIFIED_EXTRACTION',
            'display_statement':'\n'.join(item['text'] for item in source.get('original_statements',[]))
                if not row.program_id else None}


def receipt_result(row):
    return ToolResult(data={'operation_ref':'operation:'+str(row.id),'outcome':row.status,'before':row.before,
                           'after':row.after,'revision':(row.after or row.before or {}).get('revision')})


class UserMemory:
    def __init__(self,factory,identities,knowledge=None):
        self.factory=factory
        self.identities=identities
        from journeyplus.knowledge.access import KnowledgePort
        self.knowledge=knowledge or KnowledgePort(factory)

    def read(self,args):
        with read_session(self.factory) as s:
            statement=select(StatusHolding).order_by(StatusHolding.created_at,StatusHolding.id)
            if not args.include_expired:
                statement=statement.where((StatusHolding.valid_until.is_(None))|(StatusHolding.valid_until>=now_utc().date()))
            if args.holding_refs:
                statement=statement.where(StatusHolding.id.in_([UUID(ref.removeprefix('holding:')) for ref in args.holding_refs]))
            rows=list(s.scalars(statement))
            if args.query:rows=[row for row in rows if canonical(args.query) in canonical(
                row.program_display_name+' '+row.tier_display_name+' '+
                ' '.join(item['text'] for item in (row.source_record or {}).get('original_statements',[])))]
            return [holding_view(r) for r in rows]

    def authorize(self,s,ctx,authorization):
        found=list(s.scalars(select(WorkspaceMessage).where(WorkspaceMessage.workspace_id==UUID(ctx.workspace_id),
                   WorkspaceMessage.id.in_([UUID(ref) for ref in authorization.message_refs]),WorkspaceMessage.role=='USER')))
        if len(found)!=len(set(authorization.message_refs)):
            raise PermissionError('Authorization must reference user messages in this workspace')
        sources = [{'id': str(row.id), 'legacy': bool(row.content.get('metadata', {}).get('legacy')),
                    'text': '\n'.join(part.get('text') or '' for part in row.content.get('content', [])
                                      if part.get('type') == 'text')} for row in found]
        bindings = []
        for quote in authorization.quotes:
            matches = [source for source in sources if quote and quote in source['text']]
            if not matches:
                raise PermissionError('Authorization quotes must occur verbatim in user messages')
            current = [source['id'] for source in matches if not source['legacy']]
            if not current:
                raise PermissionError('Imported quotations cannot authorize a new operation; quote the new user authorization')
            bindings.append({'quote': quote, 'message_refs': current})
        return {'workspace_id':ctx.workspace_id, 'turn_id':ctx.turn_id, 'call_id':ctx.call_id, 'messages':[{'id':str(row.id),'created_at':row.created_at.isoformat()} for row in found],
                'quotes':authorization.quotes,'quote_bindings':bindings,
                'original_statements':[{'message_ref':item['id'],'text':item['text']} for item in sources if not item['legacy']],
                'requested_at':now_utc().isoformat()}

    def write(self,args,ctx):
        try:
            from journeyplus.agent.adapters.transactions import transaction
            with transaction(self.factory) as s:
                s.info['user_business_journal']=True
                # Serialize only user-memory effects. No model/network work is held here.
                if s.bind.dialect.name=='postgresql':s.execute(text('SELECT pg_advisory_xact_lock(748293001)'))
                authorization=self.authorize(s,ctx,args.authorization)
                key=ctx.workspace_id+':'+args.authorization.message_refs[-1]+':'+args.operation_key
                hashed=digest(args.model_dump(mode='json',exclude_unset=True))
                existing=s.scalar(select(OperationReceipt).where(OperationReceipt.owner_key==ctx.server_owner,OperationReceipt.idempotency_key==key))
                if existing:
                    return receipt_result(existing) if existing.payload_hash==hashed else ToolResult.failure('CONFLICT','Operation key already used for different payload')
                row=s.get(StatusHolding,UUID(args.holding_ref.removeprefix('holding:')),with_for_update=True) if args.holding_ref else None
                if args.operation!='create' and (row is None or row.revision!=args.expected_revision):
                    return ToolResult(status='ERROR',error={'code':'CONFLICT','message':'Holding missing or revision changed'},data={'current':holding_view(row)})
                identity=None
                if args.identity:
                    with self.knowledge.read() as knowledge_session:
                        resolved=self.identities.resolve(knowledge_session,args.identity,require_tier=True,context=ctx)
                    if resolved['status']=='OK':
                        identity={'program_id':UUID(resolved['program_ref'][8:]),'tier_id':UUID(resolved['tier_ref'][5:]),
                            'program_display_name':resolved['program_name'],'tier_display_name':resolved['tier_name'],
                            'program_key':normalize_key(resolved['program_name']),'tier_key':normalize_tier(resolved['tier_name']),
                            'identity_status':'CONFIRMED'}
                    elif hasattr(args.identity,'program_name') and args.identity.tier_name:
                        identity={'program_id':None,'tier_id':None,'program_display_name':args.identity.program_name,
                            'tier_display_name':args.identity.tier_name,'program_key':'unresolved:'+canonical(args.identity.program_name),
                            'tier_key':canonical(args.identity.tier_name),'identity_status':'NEEDS_CONFIRMATION'}
                    else:return ToolResult.failure('INVALID_ARGUMENT','A program and tier name or uniquely bound tier is required')
                    # Original statements are selected from stored USER messages,
                    # never supplied/reworded by the model as canonical facts.
                    source_record={'original_statements':authorization['original_statements'],
                                   'extracted_identity':args.identity.model_dump(mode='json'),
                                   'binding_state':resolved['resolution_state'],
                                   'binding_basis':resolved.get('binding_basis'),
                                   'interpretation_verified':False}
                if args.operation=='create':
                    row=s.scalar(select(StatusHolding).where(StatusHolding.program_key==identity['program_key']).with_for_update())
                    if row:
                        if not row.program_id and {item['text'] for item in (row.source_record or {}).get('original_statements',[])} != {item['text'] for item in source_record['original_statements']}:
                            return ToolResult(status='ERROR',error={'code':'CONFLICT',
                                'message':'An unverified name index matches an existing statement. It does not prove the same membership; use its holding reference for an explicit update.'},
                                data={'current':holding_view(row)})
                        same=row.tier_key==identity['tier_key'] and row.valid_until==(date.fromisoformat(args.valid_until) if args.valid_until else None)
                        if not same:return ToolResult(status='ERROR',error={'code':'CONFLICT','message':'Program already has a different holding; explicit update required'},data={'current':holding_view(row)})
                before=holding_view(row)
                outcome='APPLIED'
                if args.operation=='create':
                    if row:outcome='NOOP'
                    else:
                        row=StatusHolding(**identity,source_record=source_record,valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None)
                        s.add(row)
                elif args.operation=='update':
                    if identity:
                        collision=s.scalar(select(StatusHolding).where(
                            StatusHolding.program_key==identity['program_key'],StatusHolding.id!=row.id).with_for_update())
                        if collision:
                            return ToolResult(status='ERROR',error={'code':'CONFLICT',
                                'message':'Another holding already represents this program; no records were merged'},
                                data={'current':holding_view(collision)})
                        for key_name,value in identity.items():setattr(row,key_name,value)
                    if 'valid_until' in args.model_fields_set:row.valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None
                    if holding_view(row)==before:outcome='NOOP'
                    else:
                        if identity:row.source_record=source_record
                        row.revision+=1
                else:s.delete(row)
                s.flush()
                after=holding_view(row) if args.operation!='delete' else None
                receipt=OperationReceipt(owner_key=ctx.server_owner,idempotency_key=key,operation_kind='holding.'+args.operation,
                    payload_hash=hashed,status=outcome,entity_kind='HOLDING',entity_id=row.id,before=before,after=after,authorization_snapshot=authorization)
                s.add(receipt);s.flush()
                result=receipt_result(receipt)
            return result
        except PermissionError as exc:
            return ToolResult.failure('NOT_AUTHORIZED',str(exc))
