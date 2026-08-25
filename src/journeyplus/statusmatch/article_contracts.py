from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from journeyplus.contracts import MappingAvailability, StrictModel
from journeyplus.membership.contracts import MembershipMappingClaim


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
    schema_version: str = "2"
    highlights: list[StatusMatchArticleHighlight] = Field(
        default_factory=list, max_length=4
    )
    candidate_status_mappings: list[StatusMatchArticleCandidateMapping] = Field(
        default_factory=list, max_length=100
    )


class StatusMatchArticleCandidateMapping(StrictModel):
    source_program: str = Field(min_length=1, max_length=300)
    source_tiers: list[str] = Field(default_factory=list, max_length=20)
    target_tier: str = Field(min_length=1, max_length=200)
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    article_quote: str = Field(min_length=1, max_length=300)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "source_program", "target_tier", "article_quote", "conditions", "conflict_note"
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> StatusMatchArticleCandidateMapping:
        if self.availability == MappingAvailability.UNAVAILABLE:
            if self.source_tiers:
                raise ValueError("Unavailable mappings cannot list source tiers")
        elif not self.source_tiers:
            raise ValueError("Available mappings require source tiers")
        if self.availability == MappingAvailability.CONDITIONAL:
            if self.conditions is None:
                raise ValueError("Conditional mappings require conditions")
        elif self.conditions is not None:
            raise ValueError("Conditions require conditional availability")
        if self.conflict != (self.conflict_note is not None):
            raise ValueError("Mapping conflicts require a conflict_note and vice versa")
        return self


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
    mapping_claims: list[MembershipMappingClaim] = Field(default_factory=list)


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
