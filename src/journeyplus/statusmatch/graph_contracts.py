from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from journeyplus.contracts import EvidenceRef, MappingAvailability, StrictModel


class ProgramCategory(StrEnum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"
    CRUISE = "CRUISE"
    CARD = "CARD"
    UNKNOWN = "UNKNOWN"


class GraphCertainty(StrEnum):
    EXACT = "EXACT"
    WILDCARD = "WILDCARD"
    UNCERTAIN = "UNCERTAIN"


class TreeNodeState(StrEnum):
    EXPANDED = "EXPANDED"
    LEAF = "LEAF"
    CYCLE = "CYCLE"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    DEPTH_LIMIT = "DEPTH_LIMIT"
    NODE_LIMIT = "NODE_LIMIT"
    BRANCH_LIMIT = "BRANCH_LIMIT"


class MembershipProgram(StrictModel):
    key: str = Field(min_length=1, max_length=300)
    label: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    categories: list[ProgramCategory] = Field(default_factory=list, max_length=5)
    target_program: bool = False


class MembershipNode(StrictModel):
    id: str = Field(min_length=1, max_length=700)
    program_key: str = Field(min_length=1, max_length=300)
    tier_key: str = Field(min_length=1, max_length=300)
    program: str = Field(min_length=1, max_length=300)
    tier: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    categories: list[ProgramCategory] = Field(default_factory=list, max_length=5)


class MappingClaim(StrictModel):
    id: str = Field(min_length=1, max_length=500)
    watch_id: UUID
    host: str = Field(min_length=1, max_length=255)
    event_id: UUID
    fact_set_id: UUID
    source_program: str = Field(min_length=1, max_length=300)
    source_tier: str = Field(min_length=1, max_length=300)
    target_program: str = Field(min_length=1, max_length=300)
    target_tier: str = Field(min_length=1, max_length=300)
    source_category: ProgramCategory = ProgramCategory.UNKNOWN
    availability: MappingAvailability
    conditions: str | None = Field(default=None, max_length=1000)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    conflict: bool = False
    conflict_note: str | None = Field(default=None, max_length=1000)


class MembershipEdge(StrictModel):
    id: str = Field(min_length=1, max_length=1500)
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    certainties: list[GraphCertainty] = Field(min_length=1, max_length=3)
    claims: list[MappingClaim] = Field(min_length=1, max_length=100)
    conditional: bool = False
    conflict: bool = False


class MembershipRule(StrictModel):
    id: str = Field(min_length=1, max_length=1000)
    source_program_key: str | None = Field(default=None, max_length=300)
    source_category: ProgramCategory = ProgramCategory.UNKNOWN
    source_tier_key: str | None = Field(default=None, max_length=300)
    target_node_id: str = Field(min_length=1, max_length=700)
    certainty: GraphCertainty
    claims: list[MappingClaim] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def rule_has_a_safe_scope(self) -> MembershipRule:
        if self.source_program_key is None and self.source_category == ProgramCategory.UNKNOWN:
            raise ValueError("A graph rule requires a concrete program or category")
        if self.certainty == GraphCertainty.EXACT:
            raise ValueError("Exact mappings must be stored as graph edges")
        return self


class AliasAmbiguity(StrictModel):
    raw_program: str = Field(min_length=1, max_length=300)
    candidate_program_keys: list[str] = Field(min_length=2, max_length=20)


class GraphSnapshot(StrictModel):
    schema_version: str = "1"
    watch_ids: list[UUID] = Field(default_factory=list)
    event_ids: list[UUID] = Field(default_factory=list)
    fact_set_ids: list[UUID] = Field(default_factory=list)
    programs: list[MembershipProgram] = Field(default_factory=list)
    nodes: list[MembershipNode] = Field(default_factory=list)
    edges: list[MembershipEdge] = Field(default_factory=list)
    rules: list[MembershipRule] = Field(default_factory=list)
    expected_claim_ids: list[str] = Field(default_factory=list)
    unavailable_mapping_count: int = Field(default=0, ge=0)
    alias_ambiguities: list[AliasAmbiguity] = Field(default_factory=list)


class TraversalLimits(StrictModel):
    max_depth: int = Field(default=4, ge=1, le=8)
    max_nodes: int = Field(default=100, ge=1, le=500)
    max_branches: int = Field(default=20, ge=1, le=100)


class MembershipTreeNode(StrictModel):
    node: MembershipNode
    state: TreeNodeState
    children: list[MembershipTreeEdge] = Field(default_factory=list)
    omitted_count: int = Field(default=0, ge=0)


class MembershipTreeEdge(StrictModel):
    source_node_id: str = Field(min_length=1, max_length=700)
    target_node_id: str = Field(min_length=1, max_length=700)
    certainties: list[GraphCertainty] = Field(min_length=1, max_length=3)
    claims: list[MappingClaim] = Field(min_length=1, max_length=100)
    derived_from_rule: bool = False
    conditional: bool = False
    conflict: bool = False
    child: MembershipTreeNode


class MembershipTree(StrictModel):
    schema_version: str = "1"
    root: MembershipTreeNode
    limits: TraversalLimits
    occurrence_count: int = Field(ge=1)
    expanded_node_count: int = Field(ge=0)
    cycle_count: int = Field(ge=0)
    cross_reference_count: int = Field(ge=0)
    truncated_count: int = Field(ge=0)


class ClaimFidelityAudit(StrictModel):
    expected_claim_count: int = Field(ge=0)
    represented_claim_count: int = Field(ge=0)
    missing_claim_ids: list[str] = Field(default_factory=list)
    invented_claim_ids: list[str] = Field(default_factory=list)
    duplicate_claim_ids: list[str] = Field(default_factory=list)
    material_mismatch_claim_ids: list[str] = Field(default_factory=list)
    direction_mismatch_claim_ids: list[str] = Field(default_factory=list)
    missing_evidence_claim_ids: list[str] = Field(default_factory=list)
    unavailable_mapping_count: int = Field(ge=0)


class GraphTopologyAudit(StrictModel):
    program_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    self_loop_edge_ids: list[str] = Field(default_factory=list)
    strongly_connected_components: list[list[str]] = Field(default_factory=list)
    conditional_edge_count: int = Field(ge=0)
    conflicting_edge_count: int = Field(ge=0)
    wildcard_rule_count: int = Field(ge=0)
    uncertain_rule_count: int = Field(ge=0)
    alias_ambiguities: list[AliasAmbiguity] = Field(default_factory=list)
    representative_roots: list[str] = Field(default_factory=list)
    representative_cycle_count: int = Field(ge=0)
    representative_cross_reference_count: int = Field(ge=0)
    representative_truncated_count: int = Field(ge=0)


class GraphAuditReport(StrictModel):
    schema_version: str = "1"
    watch_ids: list[UUID] = Field(default_factory=list)
    event_ids: list[UUID] = Field(default_factory=list)
    fact_set_ids: list[UUID] = Field(default_factory=list)
    fidelity: ClaimFidelityAudit
    topology: GraphTopologyAudit


MembershipTreeNode.model_rebuild()
