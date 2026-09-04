from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from journeyplus.contracts import (
    Brief,
    EvidenceRef,
    FactSet,
    OpportunityKind,
    RoutePrice,
    StrictModel,
)
from journeyplus.membership.contracts import AirlineAlliance, ReachableMembershipForest
from journeyplus.opportunity_shaping import ChinaRegionAdvisory


class StatusHoldingInput(StrictModel):
    program_key: str = Field(min_length=1, max_length=300)
    tier_key: str = Field(min_length=1, max_length=300)
    valid_until: date | None = None


class StatusHoldingView(StrictModel):
    id: UUID
    node_id: str = Field(min_length=1, max_length=700)
    program_key: str
    tier_key: str
    program_display_name: str
    tier_display_name: str
    valid_until: date | None = None
    created_at: datetime
    updated_at: datetime


class ProductApplicationRoute(StrictModel):
    scope: str
    eligibility: str | None = None
    region: str | None = None
    china_advisory: ChinaRegionAdvisory
    cost: str | None = None
    prices: list[RoutePrice] = Field(default_factory=list)
    action_link: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    conflict: bool = False
    conflict_note: str | None = None


class MatchOpportunitySummary(StrictModel):
    opportunity_id: UUID
    source: str
    opportunity_kind: OpportunityKind
    program: str
    target_status: str | None = None
    summary: str
    lifecycle_status: str
    path: list[str] | None = None
    deadline: str | None = None
    conflict: bool = False


class MatchEdgeFee(StrictModel):
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    labels: list[str] = Field(min_length=1, max_length=20)


class PersonalizedMatches(StrictModel):
    schema_version: str = "1"
    holdings: list[StatusHoldingView] = Field(default_factory=list)
    forest: ReachableMembershipForest
    edge_fees: list[MatchEdgeFee] = Field(default_factory=list)
    opportunities: list[MatchOpportunitySummary] = Field(default_factory=list)


class CandidateCostPolicy(StrEnum):
    ANY = "ANY"
    FREE_ONLY = "FREE_ONLY"
    MAX_AMOUNT = "MAX_AMOUNT"


class CandidateChallengePolicy(StrEnum):
    ALLOW = "ALLOW"
    NO_CHALLENGE = "NO_CHALLENGE"


class CandidateRelativeTier(StrEnum):
    ANY = "ANY"
    HIGH = "HIGH"


class CandidateTarget(StrictModel):
    program_key: str | None = Field(default=None, min_length=1, max_length=300)
    tier_key: str | None = Field(default=None, min_length=1, max_length=300)
    alliance: AirlineAlliance | None = None
    relative_tier: CandidateRelativeTier = CandidateRelativeTier.ANY

    @model_validator(mode="after")
    def target_is_specific(self) -> "CandidateTarget":
        if self.program_key is None and self.alliance is None:
            raise ValueError("candidate target requires a program or alliance")
        if self.tier_key is not None and self.program_key is None:
            raise ValueError("tier target requires a program target")
        return self


class CandidateConstraints(StrictModel):
    cost_policy: CandidateCostPolicy = CandidateCostPolicy.ANY
    max_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=4
    )
    max_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    challenge_policy: CandidateChallengePolicy = CandidateChallengePolicy.ALLOW

    @model_validator(mode="after")
    def maximum_is_complete(self) -> "CandidateConstraints":
        needs_maximum = self.cost_policy == CandidateCostPolicy.MAX_AMOUNT
        if needs_maximum != (self.max_amount is not None and self.max_currency is not None):
            raise ValueError("MAX_AMOUNT requires both max_amount and max_currency")
        if not needs_maximum and (self.max_amount is not None or self.max_currency is not None):
            raise ValueError("amount and currency are only valid for MAX_AMOUNT")
        return self


class CandidateRouteQuery(StrictModel):
    target: CandidateTarget
    constraints: CandidateConstraints = Field(default_factory=CandidateConstraints)


class CandidateRouteStep(StrictModel):
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    opportunity_id: UUID
    source: str = Field(min_length=1, max_length=100)
    program: str = Field(min_length=1, max_length=300)
    target_status: str | None = Field(default=None, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
    lifecycle_status: str = Field(min_length=1, max_length=50)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    challenge_requirements: str | None = Field(default=None, max_length=2000)
    costs: list[str] = Field(default_factory=list, max_length=50)
    deadline: str | None = Field(default=None, max_length=2000)
    conflict: bool = False
    evidence_links: list[str] = Field(default_factory=list, max_length=50)
    action_links: list[str] = Field(default_factory=list, max_length=20)


class CandidateRoute(StrictModel):
    route_id: str = Field(min_length=1, max_length=100)
    node_path: list[str] = Field(min_length=2, max_length=20)
    target_program: str = Field(min_length=1, max_length=300)
    target_tier: str = Field(min_length=1, max_length=300)
    target_alliance: AirlineAlliance | None = None
    steps: list[CandidateRouteStep] = Field(min_length=1, max_length=19)
    violations: list[str] = Field(default_factory=list, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class CandidateRouteResult(StrictModel):
    schema_version: str = "1"
    query: CandidateRouteQuery
    holdings: list[StatusHoldingView] = Field(default_factory=list, max_length=100)
    matching_routes: list[CandidateRoute] = Field(default_factory=list, max_length=100)
    nearby_routes: list[CandidateRoute] = Field(default_factory=list, max_length=100)
    unknown_routes: list[CandidateRoute] = Field(default_factory=list, max_length=100)
    matching_signature: str = Field(min_length=64, max_length=64)


class OpportunityDetail(StrictModel):
    schema_version: str = "1"
    opportunity_id: UUID
    source: str
    opportunity_kind: OpportunityKind
    program: str
    target_status: str | None = None
    summary: str
    lifecycle_status: str
    path: list[str] | None = None
    facts: FactSet
    routes: list[ProductApplicationRoute] = Field(default_factory=list)
    brief: Brief | None = None
    source_links: list[str] = Field(default_factory=list)


class BriefListItem(StrictModel):
    opportunity_id: UUID
    source: str
    opportunity_kind: OpportunityKind
    program: str
    target_status: str | None = None
    lifecycle_status: str
    title: str
    summary: str
    eligibility: str | None = None
    challenge_requirements: str | None = None
    deadline: str | None = None
    price_summaries: list[str] = Field(default_factory=list)
    china_advisories: list[ChinaRegionAdvisory] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    updated_at: datetime
    path: list[str] | None = None
    reachable: bool = False


class BriefList(StrictModel):
    schema_version: str = "1"
    items: list[BriefListItem] = Field(default_factory=list)
