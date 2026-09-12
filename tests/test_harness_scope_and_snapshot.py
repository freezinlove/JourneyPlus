"""Integration boundaries found during the independent/manual audit."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,event
from journeyplus.models import AgentInteraction,now_utc
from journeyplus.agent.adapters.models import Artifact,OperationReceipt
from journeyplus.agent.tools.contracts import WaitingInput,RoutesInput,CatalogInput
from journeyplus.agent.services.snapshots import snapshot_for
from tests.test_harness_tools import context
from tests.test_knowledge_routes import edge


def test_same_call_id_across_turns_attaches_only_its_own_presentation(session_factory):
    from journeyplus.agent.composition import compose_business
    from tests.test_harness_runtime import FakeModel,answer
    def batch(title):
        return [{'type':'tool_call_ready','call_id':'shared','name':'display.present','arguments':{
            'blocks':[],'next_steps':[{'label':title,'message':title}]}},
            {'type':'turn_end','finish_reason':'tool_calls'}]
    final='{"status":"complete","parts":["已展示建议"],"deliveries":[]}'
    model=FakeModel([batch('first'),answer(final),batch('second'),answer(final)])
    runtime,store=compose_business(session_factory,model);w=store.create()
    for i in range(2):
        r=store.start(w['id'],str(i),str(i),store.read(w['id'])['revision']);asyncio.run(runtime.run(r['run_id']))
        assert store.events(w['id'],r['run_id'])[1]=='COMPLETED'
    messages=store.read(w['id'])['messages']
    attachments=[m['attachments']['presentation_refs'] for m in messages if m.get('attachments')]
    assert len(attachments)==2 and all(len(refs)==1 for refs in attachments)
    assert attachments[0]!=attachments[1]
    assert [store.artifacts.read(w['id'],refs[0])['payload']['next_steps'][0]['label'] for refs in attachments]==['first','second']


def test_waiting_durable_result_reprojects_after_workspace_expiry(session_factory):
    _,store,w,ctx=context(session_factory)
    store.start(w['id'],'Create waiting','one',0)
    ctx.turn_id=store.load_context_index(w['id'])['messages'][-1].metadata['turn_id']
    with session_factory.begin() as session:source,_=edge(session)
    waiting=ctx.services['waiting']
    args=WaitingInput(operation='create',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}})
    receipt=waiting.manage(args,ctx);assert waiting.check()['status']=='RESULT_PENDING'
    old=waiting.manage(WaitingInput(operation='list'),ctx).data['goals'][0]
    other=store.create();new_ctx=replace(ctx,workspace_id=other['id'],turn_id=str(uuid4()))
    new=waiting.manage(WaitingInput(operation='list'),new_ctx).data['goals'][0]
    assert new['result_ref']==old['result_ref'] and new['result_snapshot_ref']!=old['result_snapshot_ref']
    with pytest.raises(LookupError):store.artifacts.read(other['id'],old['result_snapshot_ref'])
    with session_factory.begin() as session:
        session.get(AgentInteraction,UUID(w['id'])).expires_at=now_utc()-timedelta(seconds=1)
        for row in session.scalars(select(Artifact).where(Artifact.workspace_id==UUID(w['id']))):row.expires_at=now_utc()-timedelta(seconds=1)
    with pytest.raises(LookupError):store.artifacts.read(w['id'],old['result_snapshot_ref'])
    assert waiting.manage(WaitingInput(operation='list'),new_ctx).data['goals'][0]['result_snapshot_ref']==new['result_snapshot_ref']
    with session_factory() as session:
        saved=session.get(OperationReceipt,UUID(receipt.data['operation_ref'].split(':')[1]))
        assert saved.status=='APPLIED' and saved.after['status']=='ACTIVE'


def test_snapshot_tracks_observations_deletions_and_avoids_immutable_scans(session_factory):
    from journeyplus.knowledge.models import Activity,ActivityObservationState,MembershipAlias
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as session:
        source,_=edge(session)
        activity=session.scalar(select(Activity))
        aid=activity.id
        session.add(ActivityObservationState(activity_id=aid,freshness='FRESH'))
    fn=snapshot_for('routes.evaluate',runtime.services['knowledge'],session_factory)
    args=RoutesInput(operation='search',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}})
    first=fn(args,ctx)
    with session_factory.begin() as session:session.get(ActivityObservationState,aid).freshness='STALE'
    assert fn(args,ctx)!=first
    with session_factory.begin() as session:session.delete(session.get(ActivityObservationState,aid))
    deleted=fn(args,ctx);assert deleted!=first
    statements=[];engine=session_factory.kw['bind']
    def capture(conn,cursor,statement,params,context,many):statements.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:fn(RoutesInput(operation='inspect',route_refs=['artifact:unused#route:one']),ctx)
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert not statements
