from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from journeyplus.contracts import StatusMapping, StrictModel


class MappingSourceType(StrEnum):
    OFFICIAL = "OFFICIAL"
    THIRD_PARTY = "THIRD_PARTY"


class MappingClaimStatus(StrEnum):
    CORROBORATED = "CORROBORATED"
    CANDIDATE = "CANDIDATE"
    CONFLICTING = "CONFLICTING"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class MembershipMappingProvenance(StrictModel):
    source_type: MappingSourceType
    document_version_id: UUID
    source_url: str = Field(min_length=1)
    target_event_id: UUID
    compared_fact_set_id: UUID
    route_id: UUID | None = None
    project_host: str | None = Field(default=None, max_length=255)


class MembershipMappingClaim(StrictModel):
    claim_id: str = Field(min_length=1, max_length=128)
    target_program: str = Field(min_length=1, max_length=300)
    mapping: StatusMapping
    provenance: MembershipMappingProvenance
    status: MappingClaimStatus
    comparison_note: str = Field(min_length=1, max_length=1000)


class MembershipMappingLayer(StrictModel):
    official: bool = False
    traversable: bool = False
    claims: list[MembershipMappingClaim] = Field(default_factory=list)
