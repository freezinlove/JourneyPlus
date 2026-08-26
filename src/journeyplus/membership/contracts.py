from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from journeyplus.contracts import (
    EvidenceRef,
    MappingAvailability,
    StrictModel,
)


class MappingContributionSource(StrEnum):
    STATUSMATCH_OFFICIAL = "STATUSMATCH_OFFICIAL"
    ORDINARY_ARTICLE = "ORDINARY_ARTICLE"


class ContributionCertainty(StrEnum):
    EXACT = "EXACT"
    WILDCARD = "WILDCARD"
    UNCERTAIN = "UNCERTAIN"


class MembershipProgramCategory(StrEnum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"
    CRUISE = "CRUISE"
    CARD = "CARD"
    UNKNOWN = "UNKNOWN"


class UnifiedTreeNodeState(StrEnum):
    EXPANDED = "EXPANDED"
    LEAF = "LEAF"
    CYCLE = "CYCLE"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    DEPTH_LIMIT = "DEPTH_LIMIT"
    NODE_LIMIT = "NODE_LIMIT"
    BRANCH_LIMIT = "BRANCH_LIMIT"


class MappingContributionProvenance(StrictModel):
    subject_id: UUID
    source_document_version_id: UUID
    source_url: str = Field(min_length=1)
    fact_set_id: UUID | None = None
    event_id: UUID | None = None
    watch_id: UUID | None = None
    opportunity_id: UUID | None = None


class MembershipMappingContribution(StrictModel):
    contribution_id: str = Field(min_length=1, max_length=500)
    source: MappingContributionSource
    source_program: str = Field(min_length=1, max_length=300)
    source_tier: str = Field(min_length=1, max_length=300)
    target_program: str = Field(min_length=1, max_length=300)
    target_tier: str = Field(min_length=1, max_length=300)
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)
    certainty: ContributionCertainty = ContributionCertainty.EXACT
    source_category: MembershipProgramCategory = MembershipProgramCategory.UNKNOWN
    rule_source_program_key: str | None = Field(default=None, max_length=300)
    rule_source_tier_key: str | None = Field(default=None, max_length=300)
    visible_from_at: datetime | None = None
    visible_until_at: datetime | None = None
    provenance: MappingContributionProvenance


class ExcludedMappingContribution(StrictModel):
    subject_id: UUID
    source: MappingContributionSource
    reason: str = Field(min_length=1, max_length=100)
    detail: str | None = Field(default=None, max_length=1000)


class UnifiedMembershipNode(StrictModel):
    id: str = Field(min_length=1, max_length=700)
    program_key: str = Field(min_length=1, max_length=300)
    tier_key: str = Field(min_length=1, max_length=300)
    program: str = Field(min_length=1, max_length=300)
    tier: str = Field(min_length=1, max_length=300)
    categories: list[MembershipProgramCategory] = Field(default_factory=list)


class UnifiedTraversalLimits(StrictModel):
    max_depth: int = Field(default=4, ge=1, le=8)
    max_nodes: int = Field(default=100, ge=1, le=500)
    max_branches: int = Field(default=20, ge=1, le=100)


class UnifiedMembershipTreeNode(StrictModel):
    node: UnifiedMembershipNode
    state: UnifiedTreeNodeState
    children: list[UnifiedMembershipTreeEdge] = Field(default_factory=list)
    omitted_count: int = Field(default=0, ge=0)


class UnifiedMembershipTreeEdge(StrictModel):
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    certainties: list[ContributionCertainty] = Field(min_length=1, max_length=3)
    conditions: list[str] = Field(default_factory=list, max_length=100)
    derived_from_rule: bool = False
    conditional: bool = False
    conflict: bool = False
    child: UnifiedMembershipTreeNode


class UnifiedMembershipTree(StrictModel):
    schema_version: str = "1"
    root: UnifiedMembershipTreeNode
    limits: UnifiedTraversalLimits
    occurrence_count: int = Field(ge=1)
    expanded_node_count: int = Field(ge=0)
    cycle_count: int = Field(ge=0)
    cross_reference_count: int = Field(ge=0)
    truncated_count: int = Field(ge=0)


class UnifiedMembershipEdgeAudit(StrictModel):
    edge_id: str = Field(min_length=1, max_length=500)
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    contributions: list[MembershipMappingContribution] = Field(default_factory=list)


class UnifiedMembershipAudit(StrictModel):
    schema_version: str = "1"
    active_contribution_count: int = Field(ge=0)
    excluded_contribution_count: int = Field(ge=0)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    strongly_connected_components: list[list[str]] = Field(default_factory=list)
    edges: list[UnifiedMembershipEdgeAudit] = Field(default_factory=list)
    excluded: list[ExcludedMappingContribution] = Field(default_factory=list)
    alias_ambiguities: dict[str, list[str]] = Field(default_factory=dict)


UnifiedMembershipTreeNode.model_rebuild()
