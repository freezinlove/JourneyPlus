"""Map only the original holding columns; Agent metadata lives in receipts."""
from datetime import date, datetime
from uuid import UUID, uuid4
from sqlalchemy import Date, DateTime, String, Uuid, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from journeyplus.models import now_utc
from .artifacts import digest


class HoldingBase(DeclarativeBase):
    pass


from journeyplus.user_scope import user_id


class WorkflowHolding(HoldingBase):
    __tablename__ = 'status_holdings'
    __table_args__ = (UniqueConstraint('user_id','program_key'),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, default=user_id, nullable=False, index=True)
    program_key: Mapped[str] = mapped_column(String(300))
    tier_key: Mapped[str] = mapped_column(String(300))
    program_display_name: Mapped[str] = mapped_column(String(300))
    tier_display_name: Mapped[str] = mapped_column(String(300))
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


def holding_revision(row):
    # An optimistic version of the actual row, including changes by the product UI.
    from .artifacts import aware
    value = [str(row.id), row.program_key, row.tier_key, row.program_display_name,
             row.tier_display_name, str(row.valid_until),
             aware(row.updated_at).isoformat() if row.updated_at else None]
    return int(digest(value)[:12], 16)
