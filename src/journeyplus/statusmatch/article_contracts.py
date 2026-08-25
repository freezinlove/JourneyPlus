from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from journeyplus.contracts import StrictModel


class StatusMatchArticleHighlightKind(StrEnum):
    FACTUAL_DETAIL = "FACTUAL_DETAIL"
    EDITORIAL_OBSERVATION = "EDITORIAL_OBSERVATION"


class StatusMatchArticleHighlight(StrictModel):
    kind: StatusMatchArticleHighlightKind
    text: str = Field(min_length=1, max_length=1000)
    article_quote: str = Field(min_length=1, max_length=300)
    novelty_reason: str = Field(min_length=1, max_length=1000)

    @field_validator("text", "article_quote", "novelty_reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class StatusMatchArticleExtraction(StrictModel):
    schema_version: str = "1"
    highlights: list[StatusMatchArticleHighlight] = Field(
        default_factory=list, max_length=4
    )


class StatusMatchSupplementView(StrictModel):
    supplement_id: UUID
    article_document_version_id: UUID
    article_title: str
    article_url: str
    article_published_at: datetime | None = None
    fact_set_id: UUID
    brief_id: UUID
    status: str
    highlights: list[StatusMatchArticleHighlight] = Field(default_factory=list)


class StatusMatchArticleRouteView(StrictModel):
    route_id: UUID
    article_document_version_id: UUID
    article_title: str
    article_url: str
    project_host: str
    status: str
    error: str | None = None


class ComposedStatusMatchBrief(StrictModel):
    project_host: str
    event_id: UUID
    event_archived: bool
    official_fact_set_id: UUID
    official_brief_id: UUID
    official_brief: dict
    supplements: list[StatusMatchSupplementView] = Field(default_factory=list)
    routes: list[StatusMatchArticleRouteView] = Field(default_factory=list)
