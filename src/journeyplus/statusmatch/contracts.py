from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, HttpUrl, field_validator, model_validator

from journeyplus.contracts import (
    MappingAvailability,
    RoutePriceAvailability,
    StrictModel,
)


class StatusMatchPageAlias(StrEnum):
    HOME = "HOME"
    FAQ = "FAQ"
    TERMS = "TERMS"


class AliasedEvidenceRef(StrictModel):
    source: StatusMatchPageAlias
    locator: str = Field(min_length=1, max_length=500)


class AliasedFactField(StrictModel):
    value: str | None = Field(default=None, max_length=2000)
    evidence: list[AliasedEvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    alternatives: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def conflicts_need_alternatives(self) -> AliasedFactField:
        if self.conflict and len(self.alternatives) < 2:
            raise ValueError("Conflicting facts require alternatives")
        return self


class AliasedRoutePrice(StrictModel):
    target_tier: str | None = Field(default=None, max_length=200)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    availability: RoutePriceAvailability = RoutePriceAvailability.UNKNOWN
    raw_text: str = Field(default="", max_length=1000)
    evidence: list[AliasedEvidenceRef] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def amount_and_availability_are_consistent(self) -> AliasedRoutePrice:
        if self.amount is not None and self.currency is None:
            raise ValueError("Numeric route prices require an ISO currency")
        if self.availability == RoutePriceAvailability.UNAVAILABLE and self.amount is not None:
            raise ValueError("Unavailable route prices cannot expose an amount")
        return self


class AliasedApplicationRoute(StrictModel):
    scope: str = Field(min_length=1, max_length=300)
    eligibility: str | None = Field(default=None, max_length=2000)
    region: str | None = Field(default=None, max_length=1000)
    cost: str | None = Field(default=None, max_length=1000)
    prices: list[AliasedRoutePrice] = Field(default_factory=list, max_length=50)
    action_link: HttpUrl | None = None
    evidence: list[AliasedEvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def route_requires_detail_and_consistent_conflict(
        self,
    ) -> AliasedApplicationRoute:
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


class AliasedStatusMapping(StrictModel):
    source_program: str = Field(min_length=1, max_length=300)
    source_tiers: list[str] = Field(default_factory=list, max_length=20)
    target_tier: str = Field(min_length=1, max_length=200)
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    evidence: list[AliasedEvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def mapping_shape_is_consistent(self) -> AliasedStatusMapping:
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


class StatusMatchProjectIdentity(StrictModel):
    program: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=1000)
    target_status: str | None = Field(default=None, max_length=300)


class TablePriceUpdate(StrictModel):
    ref: str = Field(pattern=r"^p[1-9][0-9]*$")
    target_tier: str | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = None
    availability: RoutePriceAvailability | None = None
    raw_text: str | None = None
    clear_fields: list[Literal["target_tier", "amount", "currency", "raw_text"]] = Field(default_factory=list)


class TableRouteUpdate(StrictModel):
    """Null/omitted values inherit; repeated refs split a base route."""

    ref: str = Field(pattern=r"^r[1-9][0-9]*$")
    scope: str | None = None
    eligibility: str | None = None
    region: str | None = None
    cost: str | None = None
    action_link: HttpUrl | None = None
    conflict: bool | None = None
    conflict_note: str | None = None
    price_updates: list[TablePriceUpdate] = Field(default_factory=list)
    additional_prices: list[AliasedRoutePrice] = Field(default_factory=list)
    clear_fields: list[Literal["eligibility", "region", "cost", "action_link", "conflict_note"]] = Field(default_factory=list)


class TableMappingUpdate(StrictModel):
    ref: str = Field(pattern=r"^m[1-9][0-9]*$")
    source_program: str | None = None
    source_tiers: list[str] | None = None
    target_tier: str | None = None
    availability: MappingAvailability | None = None
    conditions: str | None = None
    conflict: bool | None = None
    conflict_note: str | None = None
    clear_fields: list[Literal["conditions", "conflict_note"]] = Field(default_factory=list)


class StatusMatchProjectExtraction(StrictModel):
    schema_version: str = "1"
    identity: StatusMatchProjectIdentity
    what_happened: AliasedFactField
    eligibility: AliasedFactField = Field(default_factory=AliasedFactField)
    target_status: AliasedFactField = Field(default_factory=AliasedFactField)
    cost: AliasedFactField = Field(default_factory=AliasedFactField)
    challenge_requirements: AliasedFactField = Field(
        default_factory=AliasedFactField
    )
    region: AliasedFactField = Field(default_factory=AliasedFactField)
    application_start: AliasedFactField = Field(default_factory=AliasedFactField)
    deadline: AliasedFactField = Field(default_factory=AliasedFactField)
    status_validity: AliasedFactField = Field(default_factory=AliasedFactField)
    action_link: AliasedFactField = Field(default_factory=AliasedFactField)
    caveats: AliasedFactField = Field(default_factory=AliasedFactField)
    application_routes: list[AliasedApplicationRoute] = Field(
        default_factory=list, max_length=20
    )
    narrative_status_mappings: list[AliasedStatusMapping] = Field(
        default_factory=list, max_length=500
    )
    route_updates: list[TableRouteUpdate] = Field(default_factory=list)
    mapping_updates: list[TableMappingUpdate] = Field(default_factory=list)

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

    @field_validator(
        "application_routes", "narrative_status_mappings", mode="before"
    )
    @classmethod
    def explicit_null_means_no_structured_details(cls, value):
        return [] if value is None else value

    def fact_fields(self) -> dict[str, AliasedFactField]:
        return {
            name: value
            for name, value in self
            if isinstance(value, AliasedFactField)
        }


class StatusMatchFactChange(StrictModel):
    type: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=500)
    before: Any | None = None
    after: Any | None = None


class StatusMatchChangePayload(StrictModel):
    kind: str = Field(min_length=1, max_length=50)
    changes: list[StatusMatchFactChange] = Field(default_factory=list)
