from __future__ import annotations

from uuid import UUID

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import Brief, StatusMatchBrief, read_brief, FactSet, StrictModel
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
)


class ArticleOpportunityView(StrictModel):
    opportunity_id: UUID
    opportunity_index: int
    program: str
    target_status: str | None = None
    summary: str
    lifecycle_status: str
    facts: FactSet
    brief: Brief | StatusMatchBrief | None = None


class ArticleAnalysisView(StrictModel):
    analysis_id: UUID
    document_version_id: UUID
    source_item_id: UUID
    label: str
    confidence: float
    reason: str
    opportunities: list[ArticleOpportunityView] = Field(default_factory=list)


def latest_successful_article_view(
    session: Session, source_item_id: UUID | str
) -> ArticleAnalysisView | None:
    analysis = session.scalar(
        select(ArticleAnalysisRecord)
        .where(
            ArticleAnalysisRecord.source_item_id == UUID(str(source_item_id)),
            ArticleAnalysisRecord.status == "SUCCEEDED",
        )
        .order_by(ArticleAnalysisRecord.created_at.desc(), ArticleAnalysisRecord.id.desc())
        .limit(1)
    )
    if analysis is None:
        return None
    opportunities = list(
        session.scalars(
            select(ArticleOpportunityRecord)
            .where(ArticleOpportunityRecord.analysis_id == analysis.id)
            .order_by(ArticleOpportunityRecord.opportunity_index)
        )
    )
    views: list[ArticleOpportunityView] = []
    for opportunity in opportunities:
        brief_record = (
            session.get(ArticleBriefRecord, opportunity.current_brief_id)
            if opportunity.current_brief_id is not None
            else None
        )
        views.append(
            ArticleOpportunityView(
                opportunity_id=opportunity.id,
                opportunity_index=opportunity.opportunity_index,
                program=opportunity.program,
                target_status=opportunity.target_status,
                summary=opportunity.summary,
                lifecycle_status=opportunity.lifecycle_status,
                facts=FactSet.model_validate(opportunity.facts),
                brief=(
                    read_brief(brief_record.content)
                    if brief_record is not None
                    else None
                ),
            )
        )
    return ArticleAnalysisView(
        analysis_id=analysis.id,
        document_version_id=analysis.document_version_id,
        source_item_id=analysis.source_item_id,
        label=analysis.label,
        confidence=analysis.confidence,
        reason=analysis.reason,
        opportunities=views,
    )


def article_analysis_history(
    session: Session, source_item_id: UUID | str
) -> tuple[ArticleAnalysisRecord, ...]:
    """Return immutable document-version analyses for audit, newest first."""
    return tuple(
        session.scalars(
            select(ArticleAnalysisRecord)
            .where(
                ArticleAnalysisRecord.source_item_id == UUID(str(source_item_id))
            )
            .order_by(
                ArticleAnalysisRecord.created_at.desc(),
                ArticleAnalysisRecord.id.desc(),
            )
        )
    )
