from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator, model_validator

from journeyplus.contracts import (
    DocumentLabel,
    MappingAvailability,
    OpportunityKind,
    RoutePriceAvailability,
    StrictModel,
)


class TitleScreenDecision(StrEnum):
    PASS = "PASS"
    DROP = "DROP"
    NEEDS_BODY = "NEEDS_BODY"


class TitleScreenResult(StrictModel):
    document_version_id: UUID
    decision: TitleScreenDecision
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class TitleScreenBatch(StrictModel):
    items: list[TitleScreenResult] = Field(min_length=1, max_length=50)


class EvidenceQuote(StrictModel):
    quote: str = Field(min_length=1, max_length=480)
    locator: str | None = Field(default=None, max_length=500)


class ExtractedFactField(StrictModel):
    value: str | None = Field(default=None, max_length=2000)
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    alternatives: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def conflicts_need_alternatives(self) -> ExtractedFactField:
        if self.conflict and len(self.alternatives) < 2:
            raise ValueError("Conflicting facts require alternatives")
        return self


class ExtractedRoutePrice(StrictModel):
    target_tier: str | None = Field(default=None, max_length=200)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    availability: RoutePriceAvailability = RoutePriceAvailability.UNKNOWN
    raw_text: str = Field(default="", max_length=1000)
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def amount_and_availability_are_consistent(self) -> ExtractedRoutePrice:
        if self.amount is not None and self.currency is None:
            raise ValueError("Numeric route prices require an ISO currency")
        if self.availability == RoutePriceAvailability.UNAVAILABLE and self.amount is not None:
            raise ValueError("Unavailable route prices cannot expose an amount")
        return self


class ExtractedApplicationRoute(StrictModel):
    scope: str = Field(min_length=1, max_length=300)
    eligibility: str | None = Field(default=None, max_length=2000)
    region: str | None = Field(default=None, max_length=1000)
    cost: str | None = Field(default=None, max_length=1000)
    prices: list[ExtractedRoutePrice] = Field(default_factory=list, max_length=50)
    action_link: HttpUrl | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def route_is_actionable_and_consistent(self) -> ExtractedApplicationRoute:
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
            raise ValueError("Application route requires at least one scoped detail")
        if self.conflict != (self.conflict_note is not None):
            raise ValueError("Route conflicts require a conflict_note and vice versa")
        return self


class ExtractedStatusMapping(StrictModel):
    source_program: str = Field(min_length=1, max_length=300)
    source_tiers: list[str] = Field(default_factory=list, max_length=20)
    target_tier: str = Field(min_length=1, max_length=200)
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> ExtractedStatusMapping:
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


class ArticleOpportunityExtraction(StrictModel):
    opportunity_index: int = Field(ge=0, le=19)
    opportunity_kind: OpportunityKind = OpportunityKind.OTHER
    program: str = Field(min_length=1, max_length=300)
    target_status_name: str | None = Field(default=None, max_length=300)
    summary: str = Field(min_length=1, max_length=500)
    what_happened: ExtractedFactField
    eligibility: ExtractedFactField = Field(default_factory=ExtractedFactField)
    target_status: ExtractedFactField = Field(default_factory=ExtractedFactField)
    cost: ExtractedFactField = Field(default_factory=ExtractedFactField)
    challenge_requirements: ExtractedFactField = Field(
        default_factory=ExtractedFactField
    )
    region: ExtractedFactField = Field(default_factory=ExtractedFactField)
    application_start: ExtractedFactField = Field(default_factory=ExtractedFactField)
    deadline: ExtractedFactField = Field(default_factory=ExtractedFactField)
    status_validity: ExtractedFactField = Field(default_factory=ExtractedFactField)
    action_link: ExtractedFactField = Field(default_factory=ExtractedFactField)
    caveats: ExtractedFactField = Field(default_factory=ExtractedFactField)
    application_routes: list[ExtractedApplicationRoute] = Field(
        default_factory=list, max_length=20
    )
    status_mappings: list[ExtractedStatusMapping] = Field(
        default_factory=list, max_length=500
    )

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

    @field_validator("application_routes", "status_mappings", mode="before")
    @classmethod
    def explicit_null_means_no_structured_details(cls, value):
        return [] if value is None else value

    @model_validator(mode="after")
    def opportunity_requires_grounded_core(self) -> ArticleOpportunityExtraction:
        if self.what_happened.value is None:
            raise ValueError("Article opportunity requires grounded what_happened")
        return self

    def fact_fields(self) -> dict[str, ExtractedFactField]:
        return {
            name: value
            for name, value in self
            if isinstance(value, ExtractedFactField)
        }


class ArticleInterpretation(StrictModel):
    label: DocumentLabel
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1000)
    opportunities: list[ArticleOpportunityExtraction] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def label_matches_opportunities(self) -> ArticleInterpretation:
        if self.label == DocumentLabel.STATUS_OPPORTUNITY and not self.opportunities:
            raise ValueError("STATUS_OPPORTUNITY requires opportunities")
        if self.label != DocumentLabel.STATUS_OPPORTUNITY and self.opportunities:
            raise ValueError("Only STATUS_OPPORTUNITY may contain opportunities")
        indexes = [item.opportunity_index for item in self.opportunities]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Opportunity indexes must be unique")
        if indexes and sorted(indexes) != list(range(len(indexes))):
            raise ValueError("Opportunity indexes must be consecutive from zero")
        return self
