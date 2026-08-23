from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.models import (
    AnalysisRun,
    AutomationLease,
    AutomationRun,
    BriefRecord,
    CollectionRun,
    DocumentVersion,
    EventEvidence,
    EventRevision,
    FactSetRecord,
    GoldCaseRecord,
    InitializationRun,
    JobRun,
    ReviewDecision,
    Source,
    SourceAutomationState,
    SourceItem,
    StatusEvent,
)


DERIVED_RESET_CONFIRMATION = "RESET_DERIVED_MEMBERSHIP_DATA"


@dataclass(frozen=True, slots=True)
class DerivedResetSummary:
    deleted: dict[str, int]
    preserved: dict[str, int]


def reset_membership_derived_data(
    session_factory: sessionmaker[Session],
    *,
    confirmation: str,
    now: datetime | None = None,
) -> DerivedResetSummary:
    if confirmation != DERIVED_RESET_CONFIRMATION:
        raise ValueError("explicit derived-data reset confirmation is required")
    current = _as_utc(now or datetime.now(UTC))
    with session_factory.begin() as session:
        automatic_sources = list(
            session.scalars(
                select(Source.id).where(Source.automatic_scheduling.is_(True))
            )
        )
        if automatic_sources:
            raise RuntimeError(
                "derived data cannot be reset while automatic scheduling is enabled"
            )
        active_leases = [
            lease.name
            for lease in session.scalars(select(AutomationLease))
            if lease.owner_id is not None
            and lease.expires_at is not None
            and _as_utc(lease.expires_at) > current
        ]
        if active_leases:
            raise RuntimeError(
                "derived data cannot be reset while an automation lease is active"
            )

        preserved = {
            model.__tablename__: int(
                session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (
                Source,
                SourceItem,
                DocumentVersion,
                CollectionRun,
                GoldCaseRecord,
            )
        }
        session.execute(update(StatusEvent).values(merged_into_id=None))
        deleted: dict[str, int] = {}
        for model in (
            BriefRecord,
            FactSetRecord,
            EventRevision,
            EventEvidence,
            AnalysisRun,
            ReviewDecision,
            StatusEvent,
            JobRun,
            InitializationRun,
            AutomationRun,
            SourceAutomationState,
            AutomationLease,
        ):
            result = session.execute(delete(model))
            deleted[model.__tablename__] = int(result.rowcount or 0)
        return DerivedResetSummary(deleted=deleted, preserved=preserved)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
