"""One deterministic published query service for tools and waiting checks."""
from uuid import UUID
from datetime import date
from journeyplus.knowledge.routes import RouteService, RouteQuery, HoldingSnapshot
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.models import now_utc


class RouteQueries:
    def __init__(self,knowledge,user_data,identities):
        self.knowledge=knowledge
        self.user_data=user_data
        self.identities=identities

    def evaluate(self,query,*,context=None,limit=10):
        unresolved=[];sources=[]
        with self.knowledge.read() as s:
            identities=list(query.sources.identities)
            holdings=self.user_data.route_sources(query.sources.mode,query.sources.holding_refs)
            for holding in holdings:
                if holding['valid_until'] and date.fromisoformat(holding['valid_until'])<now_utc().date():
                    unresolved.append({**holding,'code':'HOLDING_EXPIRED'})
                elif holding['tier_ref']:
                    identities.append({'ref':holding['tier_ref']})
                else:
                    unresolved.append({**holding,'code':'CATALOG_GAP'})
            for identity in identities:
                resolved=self.identities.resolve(s,identity,require_tier=True,context=context)
                if resolved['status']!='OK':unresolved.append(resolved)
                else:sources.append(resolved)
            target=self.identities.resolve(s,query.target,context=context) if query.target else None
            # Resolution happens before the knowledge-only route query. Its
            # saved-holding counter cannot see identities excluded here.
            unresolved_holding_count=len({item['holding_ref'] for item in unresolved if item.get('holding_ref')})
            if target and target['status']!='OK':
                return {'error':ToolResult.failure(target['code'],'Target identity could not be bound',status=target['status'],candidates=target['candidates'])}
            if unresolved and (query.sources.mode=='explicit' or not sources):
                ambiguous=any(item.get('status')=='AMBIGUOUS' for item in unresolved)
                return {'error':ToolResult(status='AMBIGUOUS' if ambiguous else 'NOT_FOUND',
                    data={'resolved_sources':sources,'unresolved_sources':unresolved},
                    error={'code':'IDENTITY_AMBIGUOUS' if ambiguous else 'CATALOG_GAP',
                           'message':'Requested sources could not all be resolved',
                           'candidates':[candidate for item in unresolved for candidate in item.get('candidates',[])][:10]},
                    coverage={'complete':False,'returned':0,'total':None,'omissions':['unresolved_query_sources'],
                              'unresolved_holding_count':unresolved_holding_count})}
            actual=RouteQuery(starting_tier_ids=sorted({UUID(r['tier_ref'][5:]) for r in sources},key=str), use_saved_holdings=False,
                target_program_id=UUID(target['program_ref'][8:]) if target else None,
                target_tier_id=UUID(target['tier_ref'][5:]) if target and target['tier_ref'] else None,
                alliance=query.alliance,category=query.category,preferences=query.preferences,**query.constraints.model_dump())
            snapshot=[HoldingSnapshot(UUID(holding['holding_ref'].removeprefix('holding:')),
                        UUID(holding['tier_ref'].removeprefix('tier:')) if holding['tier_ref'] else None,
                        holding['revision'],date.fromisoformat(holding['valid_until']) if holding['valid_until'] else None)
                      for holding in holdings]
            result=RouteService(s,holding_snapshot=snapshot).query(actual,shortlist=limit)
            result['coverage']['unresolved_holding_count']=unresolved_holding_count
            if unresolved_holding_count:
                result['coverage'].setdefault('searched_published_graph_complete',result['coverage']['search_complete'])
                result['coverage']['search_complete']=False
                result['coverage']['stopped_reason']=result['coverage'].get('stopped_reason') or 'CATALOG_METADATA_GAPS'
                result['status']='PARTIAL'
        return {'result':result,'actual':actual,'sources':sources,'target':target,'unresolved':unresolved,
                'holding_snapshot':holdings}
