import asyncio


def test_filter_patch_without_change_evidence_does_not_execute(session_factory):
    from tests.test_harness_memory import setup
    from journeyplus.agent.tools.contracts import RoutesInput
    from journeyplus.agent.tools.routes import evaluate
    runtime,store,w,r,ctx,args=setup(session_factory)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'none'},'category':'HOTEL'}),ctx))
    second=asyncio.run(evaluate(RoutesInput(operation='search',query_ref=first.data['query_ref'],patch={'category':None}),ctx))
    assert second.error.code=='CONSTRAINT_CHANGE_REQUIRED'
    assert second.data['query_context']['required_fields']==['/category']
    assert not second.artifact_refs


def test_constraint_conflict_survives_registered_output_validation(session_factory):
    from tests.test_harness_memory import setup
    from journeyplus.agent.tools.contracts import RoutesInput
    from journeyplus.agent.tools.routes import evaluate
    runtime,store,w,r,ctx,args=setup(session_factory)
    first=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'none'},'category':'HOTEL'}),ctx))
    validated,_=runtime.ports.registry.validate('routes.evaluate',{'operation':'search','query_ref':first.data['query_ref'],'patch':{'category':None}})
    result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error.code=='CONSTRAINT_CHANGE_REQUIRED'
    assert result.data['query_context']['required_fields']==['/category']
