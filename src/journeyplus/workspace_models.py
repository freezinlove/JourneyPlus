from __future__ import annotations

from datetime import datetime
from uuid import UUID,uuid4

from sqlalchemy import DateTime,ForeignKey,Integer,String,UniqueConstraint,Uuid
from sqlalchemy.orm import Mapped,mapped_column

from journeyplus.models import Base,TimestampMixin
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
J=JSON().with_variant(JSONB(),'postgresql')


class WorkspaceMessage(Base,TimestampMixin):
    __tablename__="agent_workspace_messages"
    __table_args__=(UniqueConstraint("workspace_id","turn_id","role","ordinal"),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    workspace_id:Mapped[UUID]=mapped_column(ForeignKey("agent_interactions.id",ondelete="CASCADE"),index=True)
    turn_id:Mapped[UUID]=mapped_column(Uuid)
    ordinal:Mapped[int]=mapped_column(Integer)
    role:Mapped[str]=mapped_column(String(20))
    content:Mapped[dict]=mapped_column(J)


class WorkspaceTurn(Base,TimestampMixin):
    __tablename__="agent_turns"
    __table_args__=(UniqueConstraint("workspace_id","client_message_id"),)
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,default=uuid4)
    workspace_id:Mapped[UUID]=mapped_column(ForeignKey("agent_interactions.id",ondelete="CASCADE"),index=True)
    client_message_id:Mapped[str]=mapped_column(String(100))
    request_hash:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(30))
    input_revision:Mapped[int]=mapped_column(Integer)
    result_revision:Mapped[int|None]=mapped_column(Integer)
    model_calls:Mapped[int]=mapped_column(Integer,default=0)
    repair_calls:Mapped[int]=mapped_column(Integer,default=0)
    error_code:Mapped[str|None]=mapped_column(String(40))
    started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
