from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    SourceItem,
)


DEFAULT_MAPPING_VISIBILITY_DAYS = 180


class ArticleVisibilityPolicy(StrEnum):
    EXPLICIT_DEADLINE = "EXPLICIT_DEADLINE"
    DEFAULT_180_DAYS = "DEFAULT_180_DAYS"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ArticleArchiveReason(StrEnum):
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    STALE_180D = "STALE_180D"
    MANUAL = "MANUAL"
    REJECTED = "REJECTED"


def calculate_mapping_visibility(
    *,
    application_deadline_at: datetime | None,
    published_at: datetime | None,
    first_collected_at: datetime,
) -> tuple[datetime, ArticleVisibilityPolicy]:
    """Calculate mapping freshness without inventing an article deadline."""

    if application_deadline_at is not None:
        return (
            as_beijing(application_deadline_at),
            ArticleVisibilityPolicy.EXPLICIT_DEADLINE,
        )
    origin = published_at or first_collected_at
    return (
        as_beijing(origin) + timedelta(days=DEFAULT_MAPPING_VISIBILITY_DAYS),
        ArticleVisibilityPolicy.DEFAULT_180_DAYS,
    )


def is_mapping_visible(
    opportunity: ArticleOpportunityRecord,
    analysis: ArticleAnalysisRecord,
    source_item: SourceItem,
    *,
    now: datetime | None = None,
    latest_successful_analysis_id: UUID | None = None,
) -> bool:
    """Return whether an ordinary article may currently contribute graph edges."""

    if analysis.status != "SUCCEEDED":
        return False
    if latest_successful_analysis_id is not None:
        if analysis.id != latest_successful_analysis_id:
            return False
    if analysis.source_item_id != source_item.id:
        return False
    if opportunity.analysis_id != analysis.id or opportunity.archived_at is not None:
        return False
    from journeyplus.lifecycle.visibility import contributes
    return contributes(opportunity, now=now)
