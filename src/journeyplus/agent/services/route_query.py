"""Shared identity preparation and deterministic published route evaluation."""
from uuid import UUID
from contextlib import nullcontext
from datetime import date
from journeyplus.knowledge.routes import RouteService, HoldingSnapshot
from journeyplus.knowledge.simple_matching import MatchingQuery as RouteQuery
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.memberships_validity import is_active_membership, membership_date


class RouteQueries:
    def __init__(self,knowledge,user_data,identities):
        self.knowledge=knowledge
        self.user_data=user_data
        self.identities=identities

    def prepare(self,query,*,context=None,_session=None):
        """Bind explicit inputs without executing a graph search or choosing candidates."""
        unresolved=[];sources=[];explicit=[];excluded=[]
        today=membership_date()
        holdings=self.user_data.route_sources(query.sources.mode,query.sources.holding_refs)
        with (nullcontext(_session) if _session is not None else self.knowledge.read()) as s:
            inputs=[(identity,None) for identity in query.sources.identities]
            for holding in holdings:
                if holding.get('resolution_state')=='INVALID_REFERENCE':
                    unresolved.append(holding)
                elif holding['valid_until'] and not is_active_membership(date.fromisoformat(holding['valid_until']),today=today):
                    expired={**holding,'code':'HOLDING_EXPIRED','resolution_state':'EXPIRED'}
                    excluded.append(expired)
                    if query.sources.mode!='saved':unresolved.append(expired)
                elif holding['tier_ref']:
                    inputs.append(({'ref':holding['tier_ref']},holding))
                else:unresolved.append({**holding,'code':'CATALOG_GAP','resolution_state':'NOT_INDEXED'})
            for identity,holding in inputs:
                resolved=self.identities.resolve(s,identity,require_tier=True,context=context)
                if resolved['status']!='OK':unresolved.append({**(holding or {}),**resolved})
                else:
                    sources.append(resolved)
                    if holding is None:explicit.append({'ref':resolved['tier_ref']})
            target=self.identities.resolve(s,query.target,context=context) if query.target else None
        bound=query.model_dump(mode='json')
        if query.sources.mode=='explicit' and not unresolved:
            bound['sources']={'mode':'explicit','identities':explicit,'holding_refs':list(query.sources.holding_refs)}
        if target and target['status']=='OK':bound['target']={'ref':target['tier_ref'] or target['program_ref']}
        problems=[*({'field':'sources','resolution':r} for r in unresolved),
                  *([{'field':'target','resolution':target}] if target and target['status']!='OK' else [])]
        selection={'mode':query.sources.mode,'as_of_date':today.isoformat(),
            'excluded_holdings':[{k:r[k] for k in ('holding_ref','program_name','tier_name','valid_until','code')} for r in excluded]}
        if query.sources.mode=='saved':
            selection.update(active_count=len(sources),expired_count=len(excluded),
                message=('没有有效的已保存会籍；过期记录不参与匹配。请向用户说明，不要自行改成假设持有。'
                         if not sources else '仅使用当前有效且可识别的已保存会籍；过期记录已排除。'))
        elif query.sources.mode=='explicit':selection['message']='按本次明确提供的身份查询；不代表已核实用户持有这些有效会籍。'
        else:selection['message']='本次未提供会籍起点，不代表用户持有任何会籍。'
        return {'sources':sources,'target':target,'unresolved':unresolved,'holding_snapshot':holdings,'source_selection':selection,
                'bound_query':bound,'readiness':{'ready':not problems,'issues':problems,
                'unresolved_holding_count':len({r['holding_ref'] for r in unresolved if r.get('holding_ref')}),
                'meaning':'Executable conditions, not evidence that a matching route exists.'}}

    def evaluate(self,query,*,context=None,limit=10):
        with self.knowledge.read() as session:
            return self._evaluate(query,context=context,limit=limit,session=session)

    def _evaluate(self,query,*,context,limit,session):
        if not self.identities.catalog(session)[0]:
            return {'error':ToolResult.failure('KNOWLEDGE_NOT_READY',
                'The configured catalogue has no indexed matching identities. No route search was performed. Do not infer that this membership or matching routes do not exist.',status='UNAVAILABLE')}
        prepared=self.prepare(query,context=context,_session=session)
        sources,target,unresolved,holdings=(prepared[k] for k in ('sources','target','unresolved','holding_snapshot'))
        count=len({item['holding_ref'] for item in unresolved if item.get('holding_ref')})
        invalid_target=target and target['status']!='OK'
        if invalid_target or unresolved and (query.sources.mode=='explicit' or not sources):
            problem=target if invalid_target else next((r for r in unresolved if r.get('status')=='AMBIGUOUS'),unresolved[0])
            return {**prepared,'error':ToolResult(status='AMBIGUOUS' if problem.get('status')=='AMBIGUOUS' else 'NOT_FOUND',
                data={'resolved_sources':sources,'resolved_target':target,'unresolved_sources':unresolved,
                      'readiness':{**prepared['readiness'],'issues':[
                          {'field':issue['field'],'resolution_path':'/resolved_target' if issue['field']=='target' else '/unresolved_sources/'+str(i)}
                          for i,issue in enumerate(prepared['readiness']['issues'])]}},
                error={'code':problem.get('code','CATALOG_GAP'),
                       'message':'Query identities are not bound; inspect readiness issues and candidates. No route search was performed.',
                       'candidates':[]},
                coverage={'complete':False,'returned':0,'total':None,'omissions':['unresolved_query_sources'],
                          'search_performed':False,'unresolved_holding_count':count})}
        if query.sources.mode=='saved' and not sources:
            return {**prepared,'error':ToolResult(status='EMPTY',
                data={'candidates':[],'route_refs':[],'resolved_sources':[],
                      'source_selection':prepared['source_selection']},
                coverage={'complete':True,'returned':0,'total':0,'search_performed':False,
                          'stopped_reason':'NO_ACTIVE_SAVED_HOLDINGS','omissions':[]})}
        actual=RouteQuery(starting_tier_ids=sorted({UUID(r['tier_ref'][5:]) for r in sources},key=str),use_saved_holdings=False,
            target_program_id=UUID(target['program_ref'][8:]) if target else None,
            target_tier_id=UUID(target['tier_ref'][5:]) if target and target['tier_ref'] else None,
            alliance=query.alliance,category=query.category,**query.constraints.model_dump())
        snapshot=[HoldingSnapshot(UUID(h['holding_ref'][8:]),UUID(h['tier_ref'][5:]) if h['tier_ref'] else None,
                     h['revision'],date.fromisoformat(h['valid_until']) if h['valid_until'] else None) for h in holdings]
        service=getattr(self.knowledge,'route_service',RouteService)
        result=service(session,holding_snapshot=snapshot).query(actual,shortlist=limit)
        result['coverage'].update(unresolved_holding_count=count,search_performed=True)
        if count:
            result['coverage'].setdefault('searched_published_graph_complete',result['coverage']['search_complete'])
            result['coverage']['search_complete']=False
            result['coverage']['stopped_reason']=result['coverage'].get('stopped_reason') or 'CATALOG_METADATA_GAPS'
            result['status']='PARTIAL'
        return {**prepared,'result':result,'actual':actual}
