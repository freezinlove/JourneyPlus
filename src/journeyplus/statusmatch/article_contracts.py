from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl, field_validator

from journeyplus.contracts import StrictModel


StatusMatchArticleHighlight = Annotated[str, Field(min_length=1, max_length=1000)]
StatusMatchBriefPoint = Annotated[str, Field(min_length=1, max_length=500)]


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
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    key_points: list[StatusMatchBriefPoint] = Field(default_factory=list, max_length=10)
    caveats: list[StatusMatchBriefPoint] = Field(default_factory=list, max_length=10)
    source_links: list[HttpUrl] = Field(default_factory=list, max_length=30)
    supplements: list[StatusMatchSupplementView] = Field(default_factory=list)
