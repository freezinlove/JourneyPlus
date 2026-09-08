from uuid import UUID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.models import Base
from journeyplus.agent.delivery import DeliveryService
from journeyplus.agent.workspace import WorkspaceService
from journeyplus.agent.workspace_contracts import MessageRequest
from journeyplus.ai.provider import SequenceAIProvider


def test_delivery_persists_terminal_and_resumes_without_duplicate_turn(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'delivery.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    service=WorkspaceService(sessionmaker(engine,expire_on_commit=False),SequenceAIProvider([{'action':'ANSWER','payload':{'text':'你好。'}}]))
    delivery=DeliveryService(service);w=service.create();req=MessageRequest(text='你好',client_message_id='one',expected_revision=w['revision'])
    run=delivery.start(UUID(w['id']),req);delivery.pool.shutdown(wait=True)
    events,status=delivery.events(UUID(w['id']),UUID(run['run_id']))
    assert status=='COMPLETED' and events[-1]['type']=='completed'
    assert delivery.start(UUID(w['id']),req)['run_id']==run['run_id']
    assert delivery.events(UUID(w['id']),UUID(run['run_id']),events[-1]['seq'])[0]==[]
    assert len(service.read(UUID(w['id']))['messages'])==2
    engine.dispose()


def test_stale_delivery_is_marked_incomplete_once(tmp_path):
    from datetime import datetime,UTC,timedelta
    from journeyplus.agent.delivery import DeliveryRun
    engine=create_engine('sqlite:///'+str(tmp_path/'stale.db'))
    Base.metadata.create_all(engine);factory=sessionmaker(engine,expire_on_commit=False)
    service=WorkspaceService(factory,SequenceAIProvider([]));delivery=DeliveryService(service);w=service.create()
    with factory.begin() as s:
        r=DeliveryRun(workspace_id=UUID(w['id']),client_message_id='stale',request={},updated_at=datetime.now(UTC)-timedelta(seconds=120))
        s.add(r);s.flush();id=r.id
    events,status=delivery.events(UUID(w['id']),id)
    assert status=='FAILED' and len(events)==1 and events[0]['type']=='failed'
    assert delivery.events(UUID(w['id']),id,events[0]['seq'])[0]==[]
    delivery.pool.shutdown();engine.dispose()


def test_failed_partial_stream_is_durable_and_expires_with_workspace(tmp_path):
    from contextlib import nullcontext
    from datetime import datetime,UTC,timedelta
    from sqlalchemy import select,func
    from journeyplus.agent.delivery import DeliveryRun,DeliveryEvent
    from journeyplus.models import AgentInteraction
    class Broken(SequenceAIProvider):
        last_call_metrics={'stream':True}
        def call_timeout(self,*args):return nullcontext()
        def stream_text(self,**kwargs):
            yield '你好。'
            raise RuntimeError('MODEL_STREAM_INCOMPLETE')
    engine=create_engine('sqlite:///'+str(tmp_path/'broken.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine);factory=sessionmaker(engine,expire_on_commit=False)
    service=WorkspaceService(factory,Broken([]));delivery=DeliveryService(service);w=service.create()
    run=delivery.start(UUID(w['id']),MessageRequest(text='你好',client_message_id='broken',expected_revision=w['revision']))
    delivery.pool.shutdown(wait=True)
    events,status=delivery.events(UUID(w['id']),UUID(run['run_id']))
    assert status=='FAILED' and any(e['type']=='text_delta' for e in events)
    answer=events[-1]['payload']['workspace']['messages'][-1]
    assert answer['text'].startswith('你好。') and answer['error']
    with factory.begin() as s:s.get(AgentInteraction,UUID(w['id'])).expires_at=datetime.now(UTC)-timedelta(seconds=1)
    service.cleanup()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(DeliveryRun))==0
        assert s.scalar(select(func.count()).select_from(DeliveryEvent))==0
    engine.dispose()
