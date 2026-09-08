"""Durable workspace delivery events, independent from browser connections."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,UTC,timedelta
from uuid import UUID,uuid4
from sqlalchemy import ForeignKey,Integer,String,DateTime,Uuid,UniqueConstraint,select,func
from sqlalchemy.orm import Mapped,mapped_column
from journeyplus.models import Base
from journeyplus.knowledge.models import J
from journeyplus.agent.workspace_contracts import MessageRequest


class DeliveryRun(Base):
    __tablename__='agent_delivery_runs'
    __table_args__=(UniqueConstraint('workspace_id','client_message_id'),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    workspace_id:Mapped[UUID]=mapped_column(ForeignKey('agent_interactions.id',ondelete='CASCADE'),index=True)
    client_message_id:Mapped[str]=mapped_column(String(100))
    request:Mapped[dict]=mapped_column(J)
    status:Mapped[str]=mapped_column(String(30),default='RUNNING')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(UTC))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(UTC))


class DeliveryEvent(Base):
    __tablename__='agent_delivery_events'
    __table_args__=(UniqueConstraint('run_id','seq'),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    run_id:Mapped[UUID]=mapped_column(ForeignKey('agent_delivery_runs.id',ondelete='CASCADE'),index=True)
    seq:Mapped[int]=mapped_column(Integer)
    kind:Mapped[str]=mapped_column(String(30))
    payload:Mapped[dict]=mapped_column(J)


class DeliveryService:
    def __init__(self,workspace):
        self.workspace=workspace;self.factory=workspace.factory
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='agent-delivery')

    def start(self,workspace_id,request):
        from journeyplus.agent.workspace import WorkspaceError
        with self.factory.begin() as s:
            self.workspace._load(s,workspace_id,lock=True)
            run=s.scalar(select(DeliveryRun).where(DeliveryRun.workspace_id==workspace_id,DeliveryRun.client_message_id==request.client_message_id))
            if run:
                if run.request!=request.model_dump(mode='json'):raise WorkspaceError('同一消息标识对应不同输入')
                return {'run_id':str(run.id),'status':run.status}
            run=DeliveryRun(workspace_id=workspace_id,client_message_id=request.client_message_id,request=request.model_dump(mode='json'))
            s.add(run);s.flush();id=run.id
        self.pool.submit(self._work,id,workspace_id,request)
        return {'run_id':str(id),'status':'RUNNING'}

    def emit(self,id,kind,payload):
        with self.factory.begin() as s:
            run=s.get(DeliveryRun,id,with_for_update=True)
            if run is None or run.status!='RUNNING':return
            seq=(s.scalar(select(func.max(DeliveryEvent.seq)).where(DeliveryEvent.run_id==id)) or 0)+1
            s.add(DeliveryEvent(run_id=id,seq=seq,kind=kind,payload=payload))
            run.updated_at=datetime.now(UTC)
            if kind in {'completed','failed'}:run.status=kind.upper()

    def _work(self,id,workspace_id,request):
        try:
            with self.factory() as s:
                run=s.get(DeliveryRun,id)
                if run is None or run.status!='RUNNING':return
            view=self.workspace.message(workspace_id,request,event_sink=lambda kind,payload:self.emit(id,kind,payload))
            answer=view['messages'][-1]
            self.emit(id,'failed' if answer.get('error') else 'completed',{'workspace':view})
        except Exception:
            # No exception body/credentials/provider payload in client events.
            self.emit(id,'failed',{'message':'本轮未能完成，输入已保留，可以重试。'})

    def events(self,workspace_id,id,after=0):
        from journeyplus.agent.workspace import WorkspaceError,aware
        with self.factory() as s:
            self.workspace._load(s,workspace_id)
            run=s.get(DeliveryRun,id)
            if run is None or run.workspace_id!=workspace_id:raise WorkspaceError('消息流不存在')
            status=run.status;stale=aware(run.updated_at)<datetime.now(UTC)-timedelta(seconds=110)
            items=list(s.scalars(select(DeliveryEvent).where(DeliveryEvent.run_id==id,DeliveryEvent.seq>after).order_by(DeliveryEvent.seq)))
            result=[{'seq':e.seq,'type':e.kind,'payload':e.payload} for e in items]
        if status=='RUNNING' and stale:
            self.emit(id,'failed',{'message':'处理已中断，请重试；已展示内容保留。'})
            return self.events(workspace_id,id,after)
        return result,status

    def stream(self,workspace_id,id,after=0):
        while True:
            events,status=self.events(workspace_id,id,after)
            for event in events:
                after=event['seq']
                yield f"id: {after}\ndata: {json.dumps(event,ensure_ascii=False)}\n\n"
            if status!='RUNNING':return
            yield ': heartbeat\n\n'
            time.sleep(.2)
