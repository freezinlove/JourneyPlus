from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from journeyplus.contracts import DocumentLabel, RelationshipType


class GoldModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldDocument(GoldModel):
    document_key: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    normalized_body: str = Field(min_length=1)


class GoldClassification(GoldModel):
    document_key: str
    label: DocumentLabel
    event_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_labels_match_event_membership(self) -> GoldClassification:
        if self.label == DocumentLabel.STATUS_OPPORTUNITY and not self.event_keys:
            raise ValueError(
                "STATUS_OPPORTUNITY gold labels require at least one event key"
            )
        if self.label != DocumentLabel.STATUS_OPPORTUNITY and self.event_keys:
            raise ValueError(
                "Only STATUS_OPPORTUNITY gold labels can reference event keys"
            )
        return self


class GoldRelationship(GoldModel):
    document_key: str
    event_key: str
    candidate_event_key: str | None = None
    relationship: RelationshipType


class GoldEvidence(GoldModel):
    document_key: str
    locator: str = Field(min_length=1, max_length=500)


class GoldFact(GoldModel):
    event_key: str
    field: str
    value: str | None = None
    conflict: bool = False
    alternatives: list[str] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_values_need_evidence(self) -> GoldFact:
        if (self.value is not None or self.conflict) and not self.evidence:
            raise ValueError("Gold facts with content require evidence")
        return self


class GoldCase(GoldModel):
    case_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    notes: str | None = None
    documents: list[GoldDocument] = Field(min_length=1)
    classifications: list[GoldClassification] = Field(min_length=1)
    relationships: list[GoldRelationship] = Field(default_factory=list)
    facts: list[GoldFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_known_keys(self) -> GoldCase:
        document_keys = {item.document_key for item in self.documents}
        if any(item.document_key not in document_keys for item in self.classifications):
            raise ValueError("Classification references an unknown document")
        if any(item.document_key not in document_keys for item in self.relationships):
            raise ValueError("Relationship references an unknown document")
        if any(
            evidence.document_key not in document_keys
            for fact in self.facts
            for evidence in fact.evidence
        ):
            raise ValueError("Fact evidence references an unknown document")
        return self


class GoldDataset(GoldModel):
    schema_version: Literal["2"] = "2"
    dataset_version: int = Field(ge=1)
    cases: list[GoldCase] = Field(default_factory=list)
