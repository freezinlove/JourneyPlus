from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.lifecycle.service import calculate_lifecycle
from journeyplus.models import ArticleOpportunityRecord


@dataclass(frozen=True, slots=True)
class ArticleLifecycleSummary:
    scanned: int = 0
    updated: int = 0
    expired: int = 0


def advance_article_lifecycles(
    session: Session, *, now: datetime | None = None
) -> ArticleLifecycleSummary:
    opportunities = list(session.scalars(select(ArticleOpportunityRecord)))
    updated = 0
    expired = 0
    for opportunity in opportunities:
        lifecycle = calculate_lifecycle(
            opportunity.application_start_at,
            opportunity.application_deadline_at,
            now=now,
        )
        if str(lifecycle) != opportunity.lifecycle_status:
            opportunity.lifecycle_status = lifecycle
            updated += 1
        if str(lifecycle) == "EXPIRED":
            expired += 1
    session.flush()
    return ArticleLifecycleSummary(len(opportunities), updated, expired)
