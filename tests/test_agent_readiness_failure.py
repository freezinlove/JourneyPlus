import asyncio
from journeyplus.agent.composition import compose
from tests.test_harness_runtime import FakeModel,answer
from tests.test_harness_tools import context


def test_empty_catalog_is_unavailable_not_missing_membership(session_factory):
    runtime,store,w,ctx=context(session_factory)
    assert runtime.services['knowledge'].availability()['status']=='UNAVAILABLE'
    for name,args in [('catalog.lookup',{'query':'Marriott Bonvoy'}),('routes.evaluate',{'operation':'search','query':{'sources':{'mode':'explicit','identities':[{'program_name':'万豪','tier_name':'白金'}]}}})]:
        validated,_=runtime.ports.registry.validate(name,args)
        result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
        assert result.status=='UNAVAILABLE'
        assert result.error.code=='KNOWLEDGE_NOT_READY'


def test_finalizing_accepts_natural_language_without_delivery_repair(session_factory):
    class Model(FakeModel):
        def estimate_input(self,*args):return 1000
        def estimate_final_input(self,*args):return 1000
        async def stream(self,messages,definitions,limits,cancel_token):
            assert limits['tools_allowed'] is False
            assert 'response_format' not in limits
            async for event in super().stream(messages,definitions,limits,cancel_token):yield event
    model=Model([answer('现有资料不足以确定个人资格，可以根据已取得的结果继续核实。')])
    runtime,store=compose(session_factory,model)
    runtime.budget_limits={'hard':{'input_tokens':1900}}
    w=store.create();r=store.start(w['id'],'hello','one',0)
    asyncio.run(runtime.run(r['run_id']))
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    assert len(model.inputs)==1
