import asyncio
from journeyplus.agent.composition import compose
from journeyplus.agent.harness.contracts import CompletionCheck
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


def test_finalizing_still_allows_affordable_answer_repair(session_factory):
    class Model(FakeModel):
        def estimate_input(self,*args):return 1000
        def estimate_final_input(self,*args):return 1000
    class Check:
        def check(self,text,*args):return CompletionCheck(accepted=text=='fixed',feedback=['invalid format'])
    model=Model([answer('invalid'),answer('fixed')])
    runtime,store=compose(session_factory,model);runtime.ports.completion=Check()
    runtime.budget_limits={'hard':{'input_tokens':2500}}
    w=store.create();r=store.start(w['id'],'hello','one',0)
    asyncio.run(runtime.run(r['run_id']))
    assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    assert len(model.inputs)==2


def test_raw_web_page_is_not_renderable_as_a_business_fact(session_factory):
    import json
    from journeyplus.agent.services.completion import BusinessCompletion
    _,_,_,ctx=context(session_factory)
    for kind,payload,path in [('PAGE',{'text':'navigation unrelated report'},'/text'),
            ('MATERIAL',{'data':{'page_ref':'artifact:page','text':'navigation unrelated report'}},'/data/text')]:
        ref=ctx.artifact_port.put(ctx.workspace_id,kind,payload)
        verdict=BusinessCompletion().check(json.dumps({'status':'complete','parts':[{'ref':ref,'path':path}]}),[],ctx)
        assert not verdict.accepted
