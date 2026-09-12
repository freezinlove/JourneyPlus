"""Additional boundary evidence beyond the original eleven reproductions."""
import asyncio
from dataclasses import replace
from uuid import uuid4,UUID
from sqlalchemy import create_engine,event,select,func
from sqlalchemy.orm import sessionmaker
from journeyplus.agent.adapters.models import Artifact,OperationReceipt
from journeyplus.agent.tools.contracts import DisplayInput,WorkspaceReadInput,ResearchInput,WaitingInput
from journeyplus.agent.harness.context import bounded_result
from journeyplus.agent.harness.contracts import ToolResult
from tests.test_harness_tools import context


def test_catalog_and_membership_string_queries_pass_runtime_snapshot(session_factory):
    from tests.test_knowledge_routes import edge
    with session_factory.begin() as session:edge(session)
    from journeyplus.agent.composition import compose_business
    from tests.test_harness_runtime import FakeModel,answer
    model=FakeModel([[{'type':'tool_call_ready','call_id':'catalog','name':'catalog.lookup',
                      'arguments':{'query':'Example','limit':1}},
                     {'type':'tool_call_ready','call_id':'holdings','name':'holdings.read',
                      'arguments':{'query':'Example'}},
                     {'type':'turn_end','finish_reason':'tool_calls'}],answer('{"status":"complete","parts":["没有找到对应条目"],"deliveries":[]}')])
    from journeyplus.knowledge.access import KnowledgePort
    runtime,store=compose_business(session_factory,model,knowledge_port=KnowledgePort(session_factory))
    workspace=store.create();run=store.start(workspace['id'],'Find Example','snapshot-strings',0)
    asyncio.run(runtime.run(run['run_id']))
    assert store.events(workspace['id'],run['run_id'])[1]=='COMPLETED'
    results=[part.result for message in model.inputs[-1] for part in message.content if part.type=='tool_result']
    assert len(results)==2 and all(result['status']=='EMPTY' for result in results)


def test_reused_presentation_call_is_idempotent_within_one_turn(session_factory):
    from journeyplus.agent.services.display import present
    _,store,w,ctx=context(session_factory)
    args=DisplayInput(blocks=[],next_steps=[{'label':'one','message':'one'}])
    first=asyncio.run(present(args,ctx));replay=asyncio.run(present(args,ctx))
    assert first.model_dump()==replay.model_dump()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Artifact).where(Artifact.kind=='PRESENTATION'))==1


def test_artifact_count_pages_have_no_duplicates_or_missing_records(session_factory):
    from journeyplus.agent.services.workspace import read
    _,store,w,ctx=context(session_factory)
    refs=[store.artifacts.put(w['id'],'MATERIAL',{'index':i}) for i in range(7)]
    cursor=None;seen=[]
    while True:
        result=asyncio.run(read(WorkspaceReadInput(kind='artifact',refs=refs,limit=2,cursor=cursor),ctx))
        assert result.coverage['returned']==len(result.data['artifacts'])<=2
        seen.extend(item['ref'] for item in result.data['artifacts'])
        cursor=result.next_cursor
        if not cursor:break
    assert seen==refs


def test_truncated_body_is_unknown_but_closed_body_before_footer_remains_evidence(session_factory):
    from journeyplus.agent.tools.research import parse
    _,store,w,ctx=context(session_factory)
    prefix='<article><h1>From Example Gold to Other Platinum</h1><div class="instructions">My application was approved'
    results=[]
    for html in (prefix,prefix+'</div></article><footer>cut'):
        ref=store.artifacts.put(w['id'],'PAGE',{'raw_html':html,'final_url':'https://statusmatcher.com/report/12345','raw_truncated':True})
        result=asyncio.run(parse(ResearchInput(page_refs=[ref]),ctx));results.append(result)
        assert result.status=='PARTIAL' and not result.coverage['complete']
    assert results[0].data['reports'][0]['normalized_outcome']=='UNKNOWN'
    assert results[1].data['reports'][0]['normalized_outcome']=='DIRECT_MATCH'
    assert results[1].data['reports'][0]['evidence_scope']['report_body_complete']


def test_route_projection_keeps_refs_steps_counts_together_and_defers_source_cursor():
    from journeyplus.agent.tools.projection import trim_for
    candidates=[{'ref':str(i),'step_refs':['s'+str(i)],'text':'x'*2000} for i in range(6)]
    raw=ToolResult(data={'candidates':candidates,'route_refs':[row['ref'] for row in candidates],
                        'steps':[{'ref':'s'+str(i),'text':'evidence'} for i in range(6)]},
                   coverage={'complete':False,'returned':6,'returned_count':6,'total':10,'omissions':['additional_candidates']},
                   next_cursor='source-next-page')
    projected=bounded_result(raw,'artifact:full',8000,trim=trim_for('routes.evaluate'))
    assert projected.coverage['returned']==len(projected.data['candidates'])<6
    assert projected.data['route_refs']==[row['ref'] for row in projected.data['candidates']]
    assert {step['ref'] for step in projected.data['steps']}=={sid for row in projected.data['candidates'] for sid in row['step_refs']}
    assert projected.next_cursor is None and projected.coverage['source_next_cursor']=='source-next-page'
    assert projected.coverage['source_page_coverage']['returned']==6


def test_formal_connection_never_reads_user_tables(session_factory):
    from tests.test_knowledge_routes import edge
    with session_factory.begin() as session:edge(session)
    from journeyplus.agent.composition import compose_business
    from journeyplus.agent.tools.routes import evaluate
    from journeyplus.agent.tools.contracts import RoutesInput
    from tests.test_harness_runtime import FakeModel
    knowledge_engine=create_engine(session_factory.kw['bind'].url)
    statements=[]
    @event.listens_for(knowledge_engine,'before_cursor_execute')
    def capture(connection,cursor,statement,parameters,ctx,many):
        statements.append(statement)
        assert 'status_holdings' not in statement and 'agent_wait_goals' not in statement
    from journeyplus.knowledge.access import KnowledgePort
    runtime,store=compose_business(session_factory,FakeModel([]),read_factory=sessionmaker(knowledge_engine),knowledge_port=KnowledgePort(sessionmaker(knowledge_engine)))
    _,_,_,ctx=context(session_factory)
    w=store.create();ctx=replace(ctx,workspace_id=w['id'],services=runtime.services,artifact_port=store.artifacts)
    result=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'saved'}}),ctx))
    assert result.status in {'OK','EMPTY','PARTIAL'}
    assert statements
    knowledge_engine.dispose()


def test_new_authorization_can_reference_imported_context_but_quotes_bind_new_message(session_factory):
    from tests.test_harness_memory import setup
    from journeyplus.workspace_models import WorkspaceMessage
    from journeyplus.agent.harness.contracts import ModelMessage,Part
    from journeyplus.agent.tools.contracts import Authorization
    runtime,store,w,run,ctx,args=setup(session_factory)
    with session_factory.begin() as session:
        row=session.get(WorkspaceMessage,UUID(args.authorization.message_refs[0]))
        row.content={**row.content,'metadata':{**row.content['metadata'],'legacy':True}}
    owner=str(uuid4());store.claim_run(run['run_id'],owner)
    fresh=ModelMessage(role='user',content=[Part(type='text',text='现在请保存旧消息里提到的那张金卡。')])
    store.append_message(run['run_id'],owner,fresh)
    args.authorization=Authorization(message_refs=[*args.authorization.message_refs,fresh.id],quotes=['现在请保存旧消息里提到的那张金卡。'])
    result=runtime.services['user_memory'].write(args,ctx)
    assert result.data['outcome']=='APPLIED'
    with session_factory() as session:
        row=session.scalar(select(OperationReceipt))
        assert row.authorization_snapshot['quote_bindings']==[{'quote':args.authorization.quotes[0],'message_refs':[fresh.id]}]


def test_waiting_projection_failure_keeps_commit_and_replay_repairs_view(session_factory,monkeypatch):
    from tests.test_knowledge_routes import edge
    _,store,w,ctx=context(session_factory)
    store.start(w['id'],'Create and update waiting','one',0)
    auth={'message_refs':[store.load_context_index(w['id'])['messages'][0].id],'quotes':['Create and update waiting']}
    with session_factory.begin() as session:source,_=edge(session)
    query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}
    waiting=ctx.services['waiting']
    first=waiting.manage(WaitingInput(operation='create',query=query,authorization=auth,operation_key='create'),ctx)
    assert waiting.check()['status']=='RESULT_PENDING'
    current=waiting.manage(WaitingInput(operation='list'),ctx).data['goals'][0]
    args=WaitingInput(operation='update',goal_ref=current['ref'],expected_revision=current['revision'],query=query,authorization=auth,operation_key='update')
    original=store.artifacts.put_once
    def unavailable(*args,**kwargs):raise RuntimeError('temporary projection failure')
    monkeypatch.setattr(store.artifacts,'put_once',unavailable)
    result=waiting.manage(args,ctx)
    assert result.status=='PARTIAL' and result.error is None and result.data['outcome']=='APPLIED'
    assert result.data['before']['evidence_status']=='VIEW_UNAVAILABLE'
    monkeypatch.setattr(store.artifacts,'put_once',original)
    replay=waiting.manage(args,ctx)
    assert replay.data['operation_ref']==result.data['operation_ref']
    assert replay.data['before']['result_snapshot_ref']==current['result_snapshot_ref']
    assert waiting.manage(args,ctx).data==replay.data
