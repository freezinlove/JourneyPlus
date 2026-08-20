from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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


class OpportunityType(StrEnum):
    STATUS_MATCH = "STATUS_MATCH"
    STATUS_CHALLENGE = "STATUS_CHALLENGE"
    FAST_TRACK = "FAST_TRACK"
    STATUS_RECIPROCITY = "STATUS_RECIPROCITY"
    PAID_STATUS = "PAID_STATUS"
    DIRECT_STATUS_GRANT = "DIRECT_STATUS_GRANT"
    STATUS_EXTENSION = "STATUS_EXTENSION"
    OTHER_DIRECT_STATUS = "OTHER_DIRECT_STATUS"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AnalysisStage(StrEnum):
    STATUS_RELEVANCE = "STATUS_RELEVANCE"
    EVENT_RELATIONSHIP = "EVENT_RELATIONSHIP"
    FACT_CONSOLIDATION = "FACT_CONSOLIDATION"
    BRIEF_GENERATION = "BRIEF_GENERATION"


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
    opportunity_type: OpportunityType
    summary: str = Field(min_length=1, max_length=500)
    target_status: str | None = Field(default=None, max_length=200)
    region_hint: str | None = Field(default=None, max_length=200)


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
    def known_values_need_evidence(self) -> FactField:
        if self.value is not None and not self.evidence:
            raise ValueError("Known facts require at least one evidence reference")
        if self.conflict and (len(self.alternatives) < 2 or not self.evidence):
            raise ValueError("Conflicting facts require alternatives and evidence")
        return self


class FactSet(StrictModel):
    schema_version: str = "1"
    event_id: UUID
    what_happened: FactField
    eligibility: FactField = Field(default_factory=FactField)
    target_status: FactField = Field(default_factory=FactField)
    cost: FactField = Field(default_factory=FactField)
    challenge_requirements: FactField = Field(default_factory=FactField)
    region: FactField = Field(default_factory=FactField)
    deadline: FactField = Field(default_factory=FactField)
    status_validity: FactField = Field(default_factory=FactField)
    action_link: FactField = Field(default_factory=FactField)
    caveats: FactField = Field(default_factory=FactField)

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
