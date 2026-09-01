from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from journeyplus.contracts import (
    Brief,
    EvidenceRef,
    FactSet,
    OpportunityKind,
    RoutePrice,
    StrictModel,
)
from journeyplus.membership.contracts import ReachableMembershipForest
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
    reachable: bool = False


class BriefList(StrictModel):
    schema_version: str = "1"
    items: list[BriefListItem] = Field(default_factory=list)
