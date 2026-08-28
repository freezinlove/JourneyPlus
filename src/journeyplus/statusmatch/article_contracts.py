from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from journeyplus.contracts import StrictModel


StatusMatchArticleHighlight = Annotated[str, Field(min_length=1, max_length=1000)]


class StatusMatchArticleExtraction(StrictModel):
    schema_version: str = "3"
    highlights: list[StatusMatchArticleHighlight] = Field(
        default_factory=list, max_length=4
    )

    @field_validator("highlights")
    @classmethod
    def normalize_highlights(cls, values: list[str]) -> list[str]:
        return [" ".join(value.split()) for value in values]


class StatusMatchSupplementView(StrictModel):
    article_title: str
    article_url: str
    article_published_at: datetime | None = None
    highlights: list[StatusMatchArticleHighlight] = Field(default_factory=list)


class ComposedStatusMatchBrief(StrictModel):
    project_host: str
    event_id: UUID
    event_archived: bool
    official_fact_set_id: UUID
    official_brief_id: UUID
    official_brief: dict
    supplements: list[StatusMatchSupplementView] = Field(default_factory=list)
