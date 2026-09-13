from types import SimpleNamespace as Node
from collections import Counter
import json
import pytest
from journeyplus.knowledge.simple_matching import shortest_graph, TIER_ORDERS


def run(edges, *, roots=('A',), free=False, target=None, nodes=None, **limits):
    names = set(roots)|{n for a,b,*_ in edges for n in (a,b)}
    nodes = nodes or {n:Node(program_key=n, tier_key='gold') for n in names}
    visits=Counter()
    def outgoing(source):
        visits[source]+=1
        return [(b, {'ref':a+'-'+b, 'from':a, 'to':b, 'from_tier_id':a, 'to_tier_id':b,
                'paid':bool(paid), 'activity_ref':a+b, 'version_ref':'v1','fact_refs':[a+b]})
                for a,b,paid in edges if a==source]
    result=shortest_graph(nodes, roots, outgoing, lambda n:target is None or n==target,
        free_only=free, exact_tier=target is not None, **limits)
    return result, visits


def paths(r):
    return {tuple([v['from'],*[r['server_steps'][s]['to'] for s in v['step_refs']]]) for v in r['server_routes'].values()}


def test_cycle_long_duplicate_and_prefix():
    r,v=run([('A','C',0),('A','D',0),('D','B',0),('B','C',0),('C','A',0),('C','E',0)])
    assert paths(r)=={('A','C','E'),('A','D','B')}
    assert all(n==1 for n in v.values())
    assert len(r['server_steps'])==4


def test_shared_prefix_branches():
    r,_=run([('A','C',0),('C','E',0),('C','F',0)])
    assert paths(r)=={('A','C','E'),('A','C','F')}
    assert list(r['server_steps']).count('A-C')==1


def test_multiple_roots_never_recommend_already_held():
    r,_=run([('A','B',0),('A','C',0),('B','C',0)],roots=('A','B'))
    assert len(r['server_routes'])==1
    assert all(len(path)==2 and path[-1]=='C' for path in paths(r))


def test_free_filter_before_search_keeps_longer_free_path():
    edges=[('A','C',1),('A','B',0),('B','C',0)]
    r,_=run(edges,free=True,target='C');assert paths(r)=={('A','B','C')}
    r,_=run(edges,target='C');assert paths(r)=={('A','C')}


def test_highest_target_may_require_more_hops(monkeypatch):
    monkeypatch.setitem(TIER_ORDERS,'rewards',('silver','gold','platinum'))
    nodes={n:Node(program_key='rewards' if n in 'SGP' else n,tier_key={'S':'silver','G':'gold','P':'platinum'}.get(n,'gold')) for n in 'ASGPX'}
    edges=[('A','S',0),('A','G',0),('G','P',1),('S','X',0)]
    r,_=run(edges,nodes=nodes);assert paths(r)=={('A','G','P'),('A','S','X')}
    r,_=run(edges,nodes=nodes,free=True);assert paths(r)=={('A','G'),('A','S','X')}


def test_explicit_lower_tier_not_replaced():
    r,_=run([('A','S',0),('S','G',0)],target='S');assert paths(r)=={('A','S')}


def test_unknown_order_not_guessed():
    nodes={n:Node(program_key='new' if n!='A' else 'origin',tier_key=n) for n in 'ABC'}
    r,_=run([('A','B',0),('A','C',0)],nodes=nodes)
    assert len(paths(r))==2 and r['coverage']['tier_order_unknown']==['new']


def test_no_results_and_limits_are_honest():
    r,_=run([],roots=('A',));assert not r['server_routes'] and r['coverage']['search_complete']
    r,_=run([('A','B',0),('B','C',0)],max_states=1)
    assert not r['coverage']['search_complete']


def test_many_repeated_walks_do_not_multiply_states():
    names=[str(i) for i in range(45)]
    edges=[(a,b,0) for a in names for b in names if a!=b]
    r,v=run(edges,roots=('0',))
    assert len(v)==45 and max(v.values())==1
    assert len(r['server_steps'])==44 and len(r['server_routes'])==44
    assert len(json.dumps(r))<40000


def test_optional_and_region_prices_are_not_search_branches():
    from journeyplus.contracts import FactSet, FactField, ApplicationRoute, RoutePrice
    from journeyplus.knowledge.workflow_routes import matching_paid
    from uuid import uuid4
    facts=FactSet(event_id=uuid4(),what_happened=FactField(value='match'))
    assert not matching_paid(facts,'gold')
    facts.application_routes=[ApplicationRoute(scope='one',region='Somewhere',prices=[RoutePrice(target_tier='Gold',amount=99,currency='EUR',availability='AVAILABLE')])]
    assert matching_paid(facts,'gold')
    facts.application_routes[0].prices[0].availability='CONDITIONAL'
    assert not matching_paid(facts,'gold')


def test_final_results_page_without_exploration_and_no_missing_routes():
    from journeyplus.agent.services.route_storage import save_routes
    from journeyplus.agent.tools.routes import result_page
    from types import SimpleNamespace
    records={}
    class Store:
        def put(self,w,kind,payload,**kw):
            ref='artifact:'+str(len(records));records[ref]=payload;return ref
    r,_=run([('A',str(i),0) for i in range(40)])
    payload={'matching_policy':r['matching_policy'],'query_ref':'query', 'routes':r['server_routes'],
             'steps':r['server_steps'],'route_order':list(r['server_routes']), 'coverage':r['coverage']}
    ctx=SimpleNamespace(artifact_port=Store(),workspace_id='w',call_id='c',turn_id='t')
    ref,first=save_routes(ctx,payload,max_bytes=3500)
    assert len(records)>1
    found=[];cursor=ref+'|0'
    while cursor:
        root,offset=cursor.split('|');page=records[root]
        rows,cursor=result_page(page,root,int(offset),3)
        found.extend(x['ref'].split('#route:')[1] for x in rows)
        assert set(page['steps'])=={sid for row in page['routes'].values() for sid in row['step_refs']}
    assert found==list(r['server_routes']) and len(found)==len(set(found))


def test_old_parameters_are_not_exposed():
    from journeyplus.agent.tools.contracts import RouteRequest
    from pydantic import ValidationError
    for key,value in [('residency','Greece'),('max_amount','100'),('currency','EUR')]:
        with pytest.raises(ValidationError):
            RouteRequest(sources={'mode':'saved'},constraints={key:value})


@pytest.mark.parametrize('roots', [('A','B'),('B','A')])
def test_same_highest_destination_free_source_wins(roots):
    r,_=run([('A','C',1),('B','C',0)],roots=roots,target='C')
    assert paths(r)=={('B','C')}
    assert next(iter(r['server_routes'].values()))['paid'] is False


def test_free_tie_accounts_for_entire_path_not_only_last_edge():
    r,_=run([('A','B',1),('A','C',0),('B','D',0),('C','D',0)],target='D')
    assert paths(r)=={('A','C','D')}
