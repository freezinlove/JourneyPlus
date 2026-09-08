"""Explicit waiting goals and deterministic checks; no model or workflow calls."""
from journeyplus.agent.adapters.transactions import read_session
from uuid import UUID,uuid4
from sqlalchemy import select,text
from journeyplus.models import AgentWaitGoal,StatusHolding,now_utc
from journeyplus.knowledge.routes import RouteService,RouteQuery
from journeyplus.agent.adapters.models import OperationReceipt
from journeyplus.agent.adapters.artifacts import digest
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.agent.tools.contracts import RouteRequest
from .user_memory import receipt_result
from copy import deepcopy

ACTIVE={'ACTIVE','RESULT_PENDING','NEEDS_RECONFIRMATION'}


def goal_view(row):
    return {'ref':'goal:'+str(row.id),'revision':row.revision,'status':row.status,'query':row.query,
            'conditions_schema_version':row.conditions_schema_version,
            'pending_result':row.pending_result,'result_ref':str(row.result_id) if row.result_id and row.pending_result else None}


def project_goal(goal,ctx):
    """Keep receipt state visible; move historical route evidence behind refs."""
    goal=deepcopy(goal)
    result=goal.pop('pending_result',None)
    refs=[]
    if result and goal.get('conditions_schema_version',3)!=3:
        ref=ctx.artifact_port.put_once(ctx.workspace_id,'LEGACY_IMPORT',{'pending_result':result},call_id=ctx.call_id,turn_id=ctx.turn_id)
        goal.update(legacy_result_ref=ref,result_scope='LEGACY_READ_ONLY')
        return goal,[ref]
    if result and result.get('routes'):
        query_ref=ctx.artifact_port.put_once(ctx.workspace_id,'QUERY',goal['query'],call_id=ctx.call_id,turn_id=ctx.turn_id)
        payload={**result,'query_ref':query_ref,'route_order':list(result['routes'])}
        used={sid for route in result['routes'].values() for sid in route['step_refs']}
        payload['steps']={sid:step for sid,step in result['steps'].items() if sid in used}
        ref=ctx.artifact_port.put_once(ctx.workspace_id,'ROUTES',payload,call_id=ctx.call_id,turn_id=ctx.turn_id)
        goal.update(result_snapshot_ref=ref,route_refs=[ref+'#route:'+key for key in payload['route_order']],
                    coverage=result.get('coverage'))
        refs.extend([query_ref,ref])
    return goal,refs




class WaitingService:
    def __init__(self,factory,memory,queries=None):
        self.factory=factory
        self.memory=memory
        if queries is None:
            from .route_query import RouteQueries
            from journeyplus.agent.adapters.user_data import UserData
            queries=RouteQueries(memory.knowledge,UserData(factory),memory.identities)
        self.queries=queries

    def manage(self,args,ctx):
        result = self._manage(args,ctx)
        if result.error or args.operation == 'list':return result
        for key in ('before','after'):
            if result.data.get(key):
                try:
                    result.data[key],refs=project_goal(result.data[key],ctx)
                    result.artifact_refs.extend(refs)
                except Exception:
                    # The durable operation already committed. A temporary view
                    # failure cannot turn success into a retryable write error.
                    value=deepcopy(result.data[key]);value.pop('pending_result',None)
                    value['evidence_status']='VIEW_UNAVAILABLE'
                    result.data[key]=value
                    result.status='PARTIAL'
                    result.coverage={'complete':False,'returned':0,'total':None,
                                     'omissions':['temporary_receipt_view_unavailable']}
        return result

    def _manage(self,args,ctx):
        if args.operation=='list':
            with read_session(self.factory) as s:
                from journeyplus.agent.adapters.pagination import page
                rows=list(s.scalars(select(AgentWaitGoal).order_by(AgentWaitGoal.created_at,AgentWaitGoal.id)))
                selected,cursor,total=page(rows,binding=[ctx.server_owner,'waiting.list'],
                    identity=lambda row:str(row.id)+':'+str(row.revision),cursor=args.cursor,limit=args.limit)
                goals=[goal_view(row) for row in selected]
            artifacts=[]
            projected=[]
            for goal in goals:
                value,refs=project_goal(goal,ctx);projected.append(value);artifacts.extend(refs)
            return ToolResult(status='PARTIAL' if cursor else 'OK' if goals else 'EMPTY',
                              data={'goals':projected},artifact_refs=artifacts,next_cursor=cursor,
                              coverage={'complete':not bool(cursor),'returned':len(goals),'total':total,
                                        'omissions':['additional_goals'] if cursor else []})
        query=args.query
        if args.query_ref:
            obj=ctx.artifact_port.read(ctx.workspace_id,args.query_ref)
            if obj['kind']!='QUERY':raise ValueError('query_ref must reference a QUERY')
            query=RouteRequest.model_validate(obj['payload'])
        try:
            from journeyplus.agent.adapters.transactions import transaction
            with transaction(self.factory) as s:
                s.info['user_business_journal']=True
                if s.bind.dialect.name=='postgresql':s.execute(text('SELECT pg_advisory_xact_lock(748293001)'))
                authorization=self.memory.authorize(s,ctx,args.authorization)
                key=ctx.workspace_id+':'+args.authorization.message_refs[-1]+':'+args.operation_key
                hashed=digest(args.model_dump(mode='json',exclude_unset=True))
                old=s.scalar(select(OperationReceipt).where(OperationReceipt.owner_key==ctx.server_owner,OperationReceipt.idempotency_key==key))
                if old:return receipt_result(old) if old.payload_hash==hashed else ToolResult.failure('CONFLICT','Operation key payload changed')
                if query:
                    raw=query.model_dump(mode='json')
                    with ctx.services['knowledge'].read() as knowledge_session:
                        identities=[*raw['sources']['identities'],*([raw['target']] if raw.get('target') else [])]
                        for identity in identities:
                            if identity.get('ref','').startswith('artifact:'):
                                bound=self.memory.identities.resolve(knowledge_session,identity,context=ctx)
                                if bound['status']!='OK':return ToolResult.failure('STALE_REFERENCE','Waiting query needs a durable identity')
                                identity.clear();identity['ref']=bound['tier_ref'] or bound['program_ref']
                    query=RouteRequest.model_validate(raw)
                if args.operation=='create':
                    active=s.scalar(select(AgentWaitGoal).where(AgentWaitGoal.status.in_(ACTIVE)).with_for_update())
                    if active:return ToolResult(data={'existing':goal_view(active)},error={'code':'CONFLICT','message':'An active waiting goal already exists'},status='ERROR')
                    row=AgentWaitGoal(source_interaction_id=UUID(ctx.workspace_id),status='ACTIVE',query=query.model_dump(mode='json'),conditions_schema_version=3)
                    before=None;s.add(row)
                else:
                    row=s.get(AgentWaitGoal,UUID(args.goal_ref.removeprefix('goal:')),with_for_update=True)
                    if row is None or row.revision!=args.expected_revision:return ToolResult.failure('CONFLICT','Waiting goal revision changed or missing')
                    if args.operation=='update':
                        other=s.scalar(select(AgentWaitGoal).where(AgentWaitGoal.id!=row.id,
                            AgentWaitGoal.status.in_(ACTIVE)).with_for_update())
                        if other:return ToolResult(data={'existing':goal_view(other)},
                            error={'code':'CONFLICT','message':'Another active waiting goal already exists'},status='ERROR')
                    before=goal_view(row)
                    if args.operation=='cancel':row.status='CANCELLED';row.ended_at=now_utc()
                    else:
                        row.query=query.model_dump(mode='json');row.status='ACTIVE';row.conditions_schema_version=3
                        row.ended_at=None
                    row.pending_result=None;row.result_id=None;row.last_candidate_signature=None;row.revision+=1
                s.flush()
                receipt=OperationReceipt(owner_key=ctx.server_owner,idempotency_key=key,operation_kind='waiting.'+args.operation,
                    payload_hash=hashed,status='APPLIED',entity_kind='WAIT_GOAL',entity_id=row.id,before=before,after=goal_view(row),authorization_snapshot=authorization)
                s.add(receipt);s.flush()
                # Copy committed facts before the session expires. Projection is
                # outside the user transaction and cannot hold its lock for reads.
                result=receipt_result(receipt)
            return result
        except PermissionError as exc:return ToolResult.failure('NOT_AUTHORIZED',str(exc))

    def check(self):
        with read_session(self.factory) as session:
            row=session.scalar(select(AgentWaitGoal).where(
                AgentWaitGoal.status=='ACTIVE',AgentWaitGoal.conditions_schema_version==3))
            if row is None:return {'status':'NO_ACTIVE_GOAL','model_calls':0}
            identity,revision,raw=row.id,row.revision,deepcopy(row.query)
        query=RouteRequest.model_validate(raw)
        evaluation=self.queries.evaluate(query)
        if evaluation.get('error') or evaluation['unresolved']:
            return {'status':'CATALOG_GAP','model_calls':0}
        result=evaluation['result']
        matches={key:r for key,r in result['server_routes'].items() if r['classification']=='MATCH'}
        if not matches:return {'status':'NO_HIT','model_calls':0,'coverage':result['coverage']}
        signature=digest(matches)
        from journeyplus.agent.adapters.transactions import transaction
        with transaction(self.factory) as session:
            session.info['user_business_journal']=True
            if session.bind.dialect.name=='postgresql':session.execute(text('SELECT pg_advisory_xact_lock(748293001)'))
            row=session.get(AgentWaitGoal,identity,with_for_update=True)
            if row is None or row.revision!=revision or row.status!='ACTIVE':
                return {'status':'STALE_CHECK','model_calls':0}
            if self.queries.user_data.route_sources(query.sources.mode,query.sources.holding_refs)!=evaluation['holding_snapshot']:
                return {'status':'STALE_CHECK','model_calls':0}
            if signature==row.last_candidate_signature:return {'status':'DUPLICATE','model_calls':0}
            used={sid for route in matches.values() for sid in route['step_refs']}
            row.last_candidate_signature=signature
            row.pending_result={'routes':matches,
                'steps':{sid:step for sid,step in result['server_steps'].items() if sid in used},
                'coverage':result['coverage'],
                'resolution':{'resolved_sources':evaluation['sources'],'resolved_target':evaluation['target'],
                              'unresolved_sources':evaluation['unresolved']},
                'effective_input':evaluation['actual'].model_dump(mode='json')}
            row.result_id=uuid4();row.status='RESULT_PENDING';row.revision+=1
            return {'status':row.status,'goal_ref':'goal:'+str(row.id),'model_calls':0}
