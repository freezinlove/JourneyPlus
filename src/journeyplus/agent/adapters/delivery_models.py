"""Shared delivery table definitions, independent of either decision engine."""
from datetime import datetime,UTC
from uuid import UUID,uuid4
from sqlalchemy import ForeignKey,Integer,String,DateTime,Uuid,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from journeyplus.models import Base
from journeyplus.knowledge.models import J


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
