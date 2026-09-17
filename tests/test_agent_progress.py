import journeyplus.agent.adapters.models

from journeyplus.agent.harness.progress import observe
from journeyplus.agent.harness.contracts import ToolResult

def test_missing_conditions_survive_unrelated_reads_and_clear_after_valid_search():
    state={}
    missing=ToolResult(status='PARTIAL',data={'result_interpretation':{'state':'MISSING_CONDITIONS','missing_fields':['sources']}})
    assert observe(state,'routes.evaluate',missing)
    assert observe(state,'activity.read',ToolResult(data={'activities':[1]}))
    assert observe(state,'routes.evaluate',ToolResult(data={'result_interpretation':{'state':'SEARCH_COMPLETED'}})) is None
    assert not state['blockers']

def test_empty_reads_raise_feedback_without_forcing_tools_or_answer():
    state={}
    assert observe(state,'activity.read',ToolResult(status='EMPTY')) is None
    assert 'Reassess' in observe(state,'activity.read',ToolResult(status='EMPTY'))
    assert observe(state,'activity.read',ToolResult(data={'activities':[1]})) is None

def test_missing_source_never_runs_graph_service():
    from contextlib import nullcontext
    from journeyplus.agent.services.route_query import RouteQueries
    from journeyplus.agent.tools.contracts import RouteRequest
    class Knowledge:
        def read(self): return nullcontext(object())
        def route_service(self,*a,**kw): raise AssertionError('missing source must not search')
    class Identities:
        def catalog(self,s): return ([object()],[],[])
    class Queries(RouteQueries):
        def prepare(self,*a,**kw): return dict(sources=[],target=None,unresolved=[],holding_snapshot=[],source_selection={'mode':'none'})
    result=Queries(Knowledge(),None,Identities()).evaluate(RouteRequest.model_validate({'sources':{'mode':'none'}}))['error']
    assert result.coverage['search_performed'] is False
    assert result.coverage['total'] is None
    assert result.data['readiness']['issues'][0]['field']=='sources'

def test_read_cache_reuses_nonconsecutive_results(session_factory):
    from tests.test_harness_runtime import FakeModel,call,answer,execute,Echo
    from journeyplus.agent.harness.contracts import ToolDefinition
    executed=[]
    async def read(args,ctx):
        executed.append(args.value)
        return ToolResult(status='EMPTY')
    store,w,r=execute(session_factory,FakeModel([call(value='a',id='1'),call(value='b',id='2'),call(value='a',id='3'),answer()]),
        [ToolDefinition('echo','read',Echo,read)])
    assert executed==['a','b']
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'

def test_shared_availability_is_read_once_per_projection():
    from journeyplus.agent.harness.context import project
    from journeyplus.agent.harness.contracts import ToolDefinition,Capabilities
    from tests.test_harness_runtime import Echo,echo
    reads=[]
    def availability():
        reads.append(1)
        return {'status':'AVAILABLE'}
    definitions=[ToolDefinition(name,'read',Echo,echo,availability=availability) for name in ['one','two','three']]
    project([],definitions,Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096))
    assert len(reads)==1

def test_bilingual_alias_composition_does_not_bind_unrelated_names():
    from journeyplus.membership.identity import program_record
    assert program_record('汉莎 Miles & More')['key']==program_record('汉莎')['key']
    assert program_record('万豪 Marriott Bonvoy')['key']==program_record('万豪')['key']
    assert program_record('汉莎 万豪') is None
    assert program_record('汉莎 unknown') is None
