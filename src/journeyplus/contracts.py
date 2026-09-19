from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentLabel(StrEnum):
    STATUS_OPPORTUNITY = "STATUS_OPPORTUNITY"
    NONE = "NONE"
    UNCERTAIN = "UNCERTAIN"


class RelationshipType(StrEnum):
    SAME_EVENT = "SAME_EVENT"
    UPDATE_OF = "UPDATE_OF"
    DIFFERENT_EVENT = "DIFFERENT_EVENT"
    UNCERTAIN = "UNCERTAIN"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class LifecycleStatus(StrEnum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class MappingAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONDITIONAL = "CONDITIONAL"
    UNAVAILABLE = "UNAVAILABLE"


class OpportunityKind(StrEnum):
    STATUS_MATCH = "STATUS_MATCH"
    OTHER = "OTHER"


class RoutePriceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONDITIONAL = "CONDITIONAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AnalysisStage(StrEnum):
    ARTICLE_TITLE_SCREENING = "ARTICLE_TITLE_SCREENING"
    ARTICLE_INTERPRETATION = "ARTICLE_INTERPRETATION"
    ARTICLE_BRIEF = "ARTICLE_BRIEF"
    STATUS_RELEVANCE = "STATUS_RELEVANCE"
    EVENT_RELATIONSHIP = "EVENT_RELATIONSHIP"
    FACT_CONSOLIDATION = "FACT_CONSOLIDATION"
    BRIEF_GENERATION = "BRIEF_GENERATION"
    STATUSMATCH_PROJECT_EXTRACTION = "STATUSMATCH_PROJECT_EXTRACTION"
    STATUSMATCH_ARTICLE_HIGHLIGHTS = "STATUSMATCH_ARTICLE_HIGHLIGHTS"


class ReviewAction(StrEnum):
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    REGENERATE = "REGENERATE"


class DiscoveredItem(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=500)
    discovered_url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(default="", max_length=1000)
    published_at: datetime | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    discovery_fingerprint: str | None = Field(default=None, max_length=128)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class RawDocument(StrictModel):
    source_id: str
    external_id: str
    canonical_url: str
    body: str
    content_type: str = "text/html"
    fetched_at: datetime = Field(default_factory=utc_now)
    storage_mode: str = "permitted_snapshot"
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(StrictModel):
    raw_body: str
    normalized_body: str
    raw_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    normalized_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str


class EventHint(StrictModel):
    program: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    target_status: str | None = Field(default=None, max_length=200)
    region_hint: str | None = Field(default=None, max_length=500)
    application_start: str | None = Field(default=None, max_length=200)
    application_deadline: str | None = Field(default=None, max_length=200)


class RelevanceResult(StrictModel):
    label: DocumentLabel
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    event_hints: list[EventHint] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def classification_matches_event_hints(self) -> RelevanceResult:
        if self.label == DocumentLabel.STATUS_OPPORTUNITY and not self.event_hints:
            raise ValueError(
                "STATUS_OPPORTUNITY classification requires at least one event hint"
            )
        if self.label == DocumentLabel.NONE and self.event_hints:
            raise ValueError("NONE classification cannot contain event hints")
        return self


class RelationshipResult(StrictModel):
    relationship: RelationshipType
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    candidate_event_id: UUID | None = None
    deadline_extension: bool = False

    @model_validator(mode="after")
    def deadline_extension_requires_update(self) -> RelationshipResult:
        if self.deadline_extension and self.relationship != RelationshipType.UPDATE_OF:
            raise ValueError("deadline_extension requires UPDATE_OF")
        return self


class EvidenceRef(StrictModel):
    document_version_id: UUID
    source_url: HttpUrl
    locator: str = Field(min_length=1, max_length=500)


class FactField(StrictModel):
    value: str | None = Field(default=None, max_length=2000)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    conflict: bool = False
    alternatives: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def conflicts_need_alternatives(self) -> FactField:
        if self.conflict and len(self.alternatives) < 2:
            raise ValueError("Conflicting facts require alternatives")
        return self


class RoutePrice(StrictModel):
    target_tier: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    availability: RoutePriceAvailability = RoutePriceAvailability.UNKNOWN
    raw_text: str = Field(default="", max_length=1000)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def amount_and_availability_are_consistent(self) -> RoutePrice:
        if self.amount is not None and self.currency is None:
            raise ValueError("Numeric route prices require an ISO currency")
        if self.availability == RoutePriceAvailability.UNAVAILABLE and self.amount is not None:
            raise ValueError("Unavailable route prices cannot expose a payable amount")
        return self


class ApplicationRoute(StrictModel):
    scope: str = Field(min_length=1, max_length=300)
    eligibility: str | None = Field(default=None, max_length=2000)
    region: str | None = Field(default=None, max_length=1000)
    cost: str | None = Field(default=None, max_length=1000)
    prices: list[RoutePrice] = Field(default_factory=list, max_length=50)
    action_link: HttpUrl | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def route_requires_detail_and_consistent_conflict(self) -> ApplicationRoute:
        if not any(
            value is not None
            for value in (
                self.eligibility,
                self.region,
                self.cost,
                self.prices or None,
                self.action_link,
            )
        ):
            raise ValueError("Application routes require at least one scoped detail")
        if self.conflict != (self.conflict_note is not None):
            raise ValueError("Route conflicts require a conflict_note and vice versa")
        return self


class StatusMapping(StrictModel):
    source_program: str = Field(min_length=1, max_length=300)
    source_tiers: list[str] = Field(default_factory=list, max_length=20)
    target_tier: str = Field(min_length=1, max_length=200)
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def mapping_requires_consistent_availability_and_conflict(self) -> StatusMapping:
        if self.availability == MappingAvailability.UNAVAILABLE:
            if self.source_tiers:
                raise ValueError("Unavailable mappings cannot list source tiers")
        elif not self.source_tiers:
            raise ValueError("Available mappings require at least one source tier")
        if self.availability == MappingAvailability.CONDITIONAL:
            if self.conditions is None:
                raise ValueError("Conditional mappings require conditions")
        elif self.conditions is not None:
            raise ValueError("Mapping conditions require conditional availability")
        if self.conflict != (self.conflict_note is not None):
            raise ValueError("Mapping conflicts require a conflict_note and vice versa")
        return self


class MatchingOpportunity(StrictModel):
    """An explicitly reported opportunity, never an exact tier-to-tier edge."""
    source_program: str = Field(min_length=1, max_length=300)
    source_qualification: str = Field(min_length=1, max_length=1000)
    source_tiers: list[str] = Field(default_factory=list, max_length=20)
    possible_target_tiers: list[str] = Field(min_length=1, max_length=20)
    conditions: str | None = Field(default=None, max_length=1000)


class FactSet(StrictModel):
    schema_version: str = "5"
    event_id: UUID
    opportunity_kind: OpportunityKind = OpportunityKind.OTHER
    what_happened: FactField
    eligibility: FactField = Field(default_factory=FactField)
    target_status: FactField = Field(default_factory=FactField)
    cost: FactField = Field(default_factory=FactField)
    challenge_requirements: FactField = Field(default_factory=FactField)
    region: FactField = Field(default_factory=FactField)
    application_start: FactField = Field(default_factory=FactField)
    deadline: FactField = Field(default_factory=FactField)
    status_validity: FactField = Field(default_factory=FactField)
    action_link: FactField = Field(default_factory=FactField)
    caveats: FactField = Field(default_factory=FactField)
    application_routes: list[ApplicationRoute] = Field(
        default_factory=list, max_length=20
    )
    status_mappings: list[StatusMapping] = Field(default_factory=list, max_length=500)
    matching_opportunities: list[MatchingOpportunity] = Field(default_factory=list, max_length=100)

    @field_validator(
        "eligibility",
        "target_status",
        "cost",
        "challenge_requirements",
        "region",
        "application_start",
        "deadline",
        "status_validity",
        "action_link",
        "caveats",
        mode="before",
    )
    @classmethod
    def explicit_null_means_unknown_fact(cls, value):
        return {} if value is None else value

    @field_validator("application_routes", "status_mappings", "matching_opportunities", mode="before")
    @classmethod
    def explicit_null_means_no_structured_details(cls, value):
        return [] if value is None else value

    def fact_fields(self) -> dict[str, FactField]:
        return {
            name: value
            for name, value in self
            if isinstance(value, FactField)
        }


class BriefPoint(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    fact_keys: list[str] = Field(min_length=1, max_length=10)


class Brief(StrictModel):
    schema_version: str = "1"
    fact_set_id: UUID
    title: str = Field(min_length=1, max_length=120)
    title_fact_keys: list[str] = Field(min_length=1, max_length=3)
    summary: str = Field(min_length=1, max_length=600)
    summary_fact_keys: list[str] = Field(min_length=1, max_length=10)
    key_points: list[BriefPoint] = Field(default_factory=list, max_length=10)
    caveats: list[BriefPoint] = Field(default_factory=list, max_length=10)
    source_links: list[HttpUrl] = Field(default_factory=list, max_length=30)


class StatusMatchBrief(StrictModel):
    """Official brief text; tables and personal relevance come from readers."""

    schema_version: str = "statusmatch-brief-1"
    fact_set_id: UUID
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    source_links: list[HttpUrl] = Field(default_factory=list, max_length=30)


class ArticleShortBrief(StatusMatchBrief):
    """Article copy emitted with extraction; all other fields are assembled."""

    schema_version: str = "article-short-brief-1"


def read_brief(content: dict) -> Brief | StatusMatchBrief:
    if content.get("schema_version") == "article-short-brief-1":
        return ArticleShortBrief.model_validate(content)
    if content.get("schema_version") == "statusmatch-brief-1":
        return StatusMatchBrief.model_validate(content)
    return Brief.model_validate(content)
