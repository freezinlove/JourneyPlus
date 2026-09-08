"""Atomic user-authorized effects, journal entries and durable idempotency receipts."""
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
    return {'ref':'holding:'+str(row.id),'revision':row.revision,'program_name':row.program_display_name,
            'tier_name':row.tier_display_name,'program_ref':'program:'+str(row.program_id) if row.program_id else None,
            'tier_ref':'tier:'+str(row.tier_id) if row.tier_id else None,'valid_until':row.valid_until.isoformat() if row.valid_until else None,
            'identity_status':row.identity_status}


def receipt_result(row):
    return ToolResult(data={'operation_ref':'operation:'+str(row.id),'outcome':row.status,'before':row.before,
                           'after':row.after,'revision':(row.after or row.before or {}).get('revision')})


class UserMemory:
    def __init__(self,factory,identities):
        self.factory=factory
        self.identities=identities

    def read(self,args):
        with self.factory() as s:
            rows=list(s.scalars(select(StatusHolding).order_by(StatusHolding.created_at)))
            rows=[r for r in rows if (args.include_expired or r.valid_until is None or r.valid_until>=date.today())
                  and (not args.holding_refs or 'holding:'+str(r.id) in args.holding_refs)
                  and (not args.query or canonical(args.query) in canonical(r.program_display_name+' '+r.tier_display_name))]
            return [holding_view(r) for r in rows]

    def authorize(self,s,ctx,authorization):
        found=list(s.scalars(select(WorkspaceMessage).where(WorkspaceMessage.workspace_id==UUID(ctx.workspace_id),
                   WorkspaceMessage.id.in_([UUID(ref) for ref in authorization.message_refs]),WorkspaceMessage.role=='USER')))
        if len(found)!=len(set(authorization.message_refs)):
            raise PermissionError('Authorization must reference user messages in this workspace')
        if found and all(row.content.get('metadata',{}).get('legacy') for row in found):
            raise PermissionError('Imported history alone cannot authorize a new operation')
        originals=['\n'.join(p.get('text') or '' for p in row.content.get('content',[]) if p.get('type')=='text') for row in found]
        if any(not quote or not any(quote in original for original in originals) for quote in authorization.quotes):
            raise PermissionError('Authorization quotes must occur verbatim in user messages')
        return {'workspace_id':ctx.workspace_id, 'turn_id':ctx.turn_id, 'call_id':ctx.call_id, 'messages':[{'id':str(row.id),'created_at':row.created_at.isoformat()} for row in found],
                'quotes':authorization.quotes,'requested_at':now_utc().isoformat()}

    def write(self,args,ctx):
        try:
            with self.factory.begin() as s:
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
                    resolved=self.identities.resolve(s,args.identity,require_tier=True,context=ctx)
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
                if args.operation=='create':
                    row=s.scalar(select(StatusHolding).where(StatusHolding.program_key==identity['program_key']).with_for_update())
                    if row:
                        same=row.tier_key==identity['tier_key'] and row.valid_until==(date.fromisoformat(args.valid_until) if args.valid_until else None)
                        if not same:return ToolResult(status='ERROR',error={'code':'CONFLICT','message':'Program already has a different holding; explicit update required'},data={'current':holding_view(row)})
                before=holding_view(row)
                outcome='APPLIED'
                if args.operation=='create':
                    if row:outcome='NOOP'
                    else:
                        row=StatusHolding(**identity,valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None)
                        s.add(row)
                elif args.operation=='update':
                    if identity:
                        for key_name,value in identity.items():setattr(row,key_name,value)
                    if 'valid_until' in args.model_fields_set:row.valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None
                    if holding_view(row)==before:outcome='NOOP'
                    else:row.revision+=1
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
