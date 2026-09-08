"""Additive runtime persistence. Durable operation receipts outlive workspaces."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, Integer, String, DateTime, Boolean, UniqueConstraint, Uuid, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from journeyplus.models import Base, now_utc
from journeyplus.knowledge.models import J
from .delivery_models import DeliveryRun, DeliveryEvent


class RunCheckpoint(Base):
    __tablename__ = 'agent_run_checkpoints'
    run_id: Mapped[UUID] = mapped_column(ForeignKey('agent_delivery_runs.id', ondelete='CASCADE'), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('agent_interactions.id', ondelete='CASCADE'), index=True)
    turn_id: Mapped[UUID] = mapped_column(ForeignKey('agent_turns.id', ondelete='CASCADE'))
    phase: Mapped[str] = mapped_column(String(30), default='READY_MODEL')
    model_attempt: Mapped[int] = mapped_column(Integer, default=0)
    pending_calls: Mapped[list] = mapped_column(J, default=list)
    remaining_budget: Mapped[dict] = mapped_column(J, default=dict)
    last_message_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[UUID | None] = mapped_column(Uuid)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Base):
    __tablename__ = 'agent_artifacts'
    __table_args__ = (Index('ix_agent_artifact_scope_kind_time', 'workspace_id', 'kind', 'created_at'),
        Index('uq_agent_presentation_call_scope', 'workspace_id', 'created_by_turn_id', 'created_by_call_id',
              unique=True, postgresql_where=text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL"),
              sqlite_where=text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL")),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('agent_interactions.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(J)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_refs: Mapped[list] = mapped_column(J, default=list)
    created_by_turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_by_call_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolCall(Base):
    __tablename__ = 'agent_tool_calls'
    __table_args__ = (UniqueConstraint('turn_id', 'provider_call_id'),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey('agent_interactions.id', ondelete='CASCADE'), index=True)
    turn_id: Mapped[UUID] = mapped_column(ForeignKey('agent_turns.id', ondelete='CASCADE'))
    provider_call_id: Mapped[str] = mapped_column(String(200))
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_version: Mapped[str] = mapped_column(String(30), default='1')
    arguments: Mapped[dict] = mapped_column(J)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    effect: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='PENDING')
    result_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey('agent_artifacts.id', ondelete='SET NULL'))
    operation_ref: Mapped[str | None] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict | None] = mapped_column(J)


class OperationReceipt(Base):
    __tablename__ = 'agent_operation_receipts'
    __table_args__ = (UniqueConstraint('owner_key', 'idempotency_key'),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_key: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(500))
    operation_kind: Mapped[str] = mapped_column(String(40))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    entity_kind: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    before: Mapped[dict | None] = mapped_column(J)
    after: Mapped[dict | None] = mapped_column(J)
    authorization_snapshot: Mapped[dict] = mapped_column(J)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
