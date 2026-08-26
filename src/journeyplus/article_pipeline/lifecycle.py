from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.lifecycle.service import calculate_lifecycle
from journeyplus.models import ArticleOpportunityRecord
from journeyplus.article_pipeline.visibility import (
    ArticleArchiveReason,
    ArticleVisibilityPolicy,
)
from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing


@dataclass(frozen=True, slots=True)
class ArticleLifecycleSummary:
    scanned: int = 0
    updated: int = 0
    expired: int = 0
    mapping_archived: int = 0
    archived_retained: int = 0
    failed: int = 0
    errors: tuple[str, ...] = ()


def advance_article_lifecycles(
    session: Session, *, now: datetime | None = None
) -> ArticleLifecycleSummary:
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    opportunities = list(session.scalars(select(ArticleOpportunityRecord)))
    updated = 0
    expired = 0
    mapping_archived = 0
    archived_retained = 0
    errors: list[str] = []
    for opportunity in opportunities:
        before = (
            opportunity.lifecycle_status,
            opportunity.archived_at,
            opportunity.archive_reason,
        )
        try:
            lifecycle = calculate_lifecycle(
                opportunity.application_start_at,
                opportunity.application_deadline_at,
                now=current,
            )
            opportunity.lifecycle_status = lifecycle
            if str(lifecycle) == "EXPIRED":
                expired += 1
            if opportunity.archived_at is not None:
                archived_retained += 1
            elif (
                opportunity.visibility_until_at is not None
                and current >= as_beijing(opportunity.visibility_until_at)
            ):
                opportunity.archived_at = current
                opportunity.archive_reason = (
                    ArticleArchiveReason.DEADLINE_EXPIRED
                    if opportunity.visibility_policy
                    == ArticleVisibilityPolicy.EXPLICIT_DEADLINE
                    else ArticleArchiveReason.STALE_180D
                    if opportunity.visibility_policy
                    == ArticleVisibilityPolicy.DEFAULT_180_DAYS
                    else ArticleArchiveReason.MANUAL
                )
                mapping_archived += 1
            after = (
                opportunity.lifecycle_status,
                opportunity.archived_at,
                opportunity.archive_reason,
            )
            if before != after:
                updated += 1
        except Exception as exc:
            errors.append(
                f"{opportunity.id}: {type(exc).__name__}: "
                f"{' '.join(str(exc).split())[:500]}"
            )
    session.flush()
    return ArticleLifecycleSummary(
        scanned=len(opportunities),
        updated=updated,
        expired=expired,
        mapping_archived=mapping_archived,
        archived_retained=archived_retained,
        failed=len(errors),
        errors=tuple(errors),
    )
