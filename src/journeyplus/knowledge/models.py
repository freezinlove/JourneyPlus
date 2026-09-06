from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (JSON, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

J = JSON().with_variant(JSONB(), "postgresql")

from journeyplus.models import Base, TimestampMixin


class Identity(TimestampMixin):
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class MembershipProgram(Base, Identity):
    __tablename__ = "membership_programs"
    __table_args__ = (CheckConstraint("category IN ('AIRLINE','HOTEL','CRUISE','OTHER')", name="ck_program_category"),)
    canonical_key: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="OTHER")
    alliance: Mapped[str | None] = mapped_column(String(30))
    metadata_provenance: Mapped[dict] = mapped_column(J, default=dict)


class MembershipTier(Base, Identity):
    __tablename__ = "membership_tiers"
    __table_args__ = (UniqueConstraint("program_id", "canonical_key"), UniqueConstraint("id", "program_id"))
    program_id: Mapped[UUID] = mapped_column(ForeignKey("membership_programs.id"))
    canonical_key: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    rank: Mapped[int | None] = mapped_column(Integer)
    rank_provenance: Mapped[dict | None] = mapped_column(J)


class MembershipAlias(Base, Identity):
    __tablename__ = "membership_aliases"
    __table_args__ = (
        ForeignKeyConstraint(["tier_id", "program_id"], ["membership_tiers.id", "membership_tiers.program_id"]),
        Index("ix_membership_alias_lookup", "normalized_alias"),
        Index("uq_program_alias", "normalized_alias", "program_id", unique=True,
              postgresql_where=text("tier_id IS NULL"), sqlite_where=text("tier_id IS NULL")),
        Index("uq_tier_alias", "normalized_alias", "program_id", "tier_id", unique=True,
              postgresql_where=text("tier_id IS NOT NULL"), sqlite_where=text("tier_id IS NOT NULL")),
    )
    normalized_alias: Mapped[str] = mapped_column(Text)
    program_id: Mapped[UUID] = mapped_column(ForeignKey("membership_programs.id"))
    tier_id: Mapped[UUID | None] = mapped_column(Uuid)
    locale: Mapped[str | None] = mapped_column(String(30))
    origin: Mapped[str] = mapped_column(Text)


class Activity(Base, Identity):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("kind IN ('STATUS_MATCH','OTHER')", name="ck_activity_kind"),
        ForeignKeyConstraint(["current_version_id", "id"],
                             ["activity_knowledge_versions.id", "activity_knowledge_versions.activity_id"],
                             name="fk_activity_current_version", use_alter=True),
    )
    identity_key: Mapped[str] = mapped_column(Text, unique=True)
    primary_program_id: Mapped[UUID | None] = mapped_column(ForeignKey("membership_programs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    edition_key: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    merged_into_id: Mapped[UUID | None] = mapped_column(ForeignKey("activities.id"))


class ActivityKnowledgeVersion(Base, Identity):
    __tablename__ = "activity_knowledge_versions"
    __table_args__ = (
        UniqueConstraint("activity_id", "version_no"), UniqueConstraint("activity_id", "extraction_key"),
        UniqueConstraint("id", "activity_id"),
        CheckConstraint("status IN ('DRAFT','VALIDATED','PUBLISHED','REJECTED')", name="ck_knowledge_status"),
        ForeignKeyConstraint(["base_version_id", "activity_id"], ["activity_knowledge_versions.id", "activity_knowledge_versions.activity_id"]),
        Index("ix_knowledge_activity_status", "activity_id", "status"),
    )
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    base_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    facts: Mapped[dict] = mapped_column(J)
    fact_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    extraction_key: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_errors: Mapped[list] = mapped_column(J, default=list)


class ApplicationOption(Base, Identity):
    __tablename__ = "application_options"
    __table_args__ = (UniqueConstraint("activity_id", "logical_key"), UniqueConstraint("id", "activity_id"))
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"))
    logical_key: Mapped[str] = mapped_column(Text)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationOptionVersion(Base, Identity):
    __tablename__ = "application_option_versions"
    __table_args__ = (
        UniqueConstraint("knowledge_version_id", "option_id"), UniqueConstraint("id", "knowledge_version_id"),
        ForeignKeyConstraint(["knowledge_version_id", "activity_id"], ["activity_knowledge_versions.id", "activity_knowledge_versions.activity_id"]),
        ForeignKeyConstraint(["option_id", "activity_id"], ["application_options.id", "application_options.activity_id"]),
        CheckConstraint("method IN ('MATCH','CHALLENGE','OTHER')", name="ck_option_method"),
        CheckConstraint("availability IN ('AVAILABLE','UNAVAILABLE','UNKNOWN','CONFLICT')", name="ck_option_availability"),
    )
    knowledge_version_id: Mapped[UUID] = mapped_column(Uuid)
    activity_id: Mapped[UUID] = mapped_column(Uuid)
    option_id: Mapped[UUID] = mapped_column(Uuid)
    method: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(Text)
    source_scope: Mapped[dict] = mapped_column(J)
    conditions: Mapped[dict] = mapped_column(J)
    challenge: Mapped[dict] = mapped_column(J)
    application_window: Mapped[dict] = mapped_column(J)
    status_validity: Mapped[dict] = mapped_column(J)
    action_link: Mapped[dict] = mapped_column(J)
    availability: Mapped[str] = mapped_column(String(30))


class OptionMapping(Base, Identity):
    __tablename__ = "option_mappings"
    __table_args__ = (
        UniqueConstraint("option_version_id", "semantic_key"), UniqueConstraint("id", "option_version_id"),
        ForeignKeyConstraint(["option_version_id", "knowledge_version_id"], ["application_option_versions.id", "application_option_versions.knowledge_version_id"]),
        ForeignKeyConstraint(["target_tier_id", "target_program_id"], ["membership_tiers.id", "membership_tiers.program_id"]),
        CheckConstraint("availability IN ('AVAILABLE','UNAVAILABLE','UNKNOWN','CONFLICT')", name="ck_mapping_availability"),
        Index("ix_option_mapping_target", "target_program_id", "target_tier_id"),
    )
    option_version_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_version_id: Mapped[UUID] = mapped_column(Uuid)
    source_scope: Mapped[dict] = mapped_column(J)
    target_program_id: Mapped[UUID] = mapped_column(Uuid)
    target_tier_id: Mapped[UUID] = mapped_column(Uuid)
    conditions: Mapped[dict] = mapped_column(J)
    availability: Mapped[str] = mapped_column(String(30))
    evidence_ids: Mapped[list] = mapped_column(J)
    semantic_key: Mapped[str] = mapped_column(Text)


class OptionPrice(Base, Identity):
    __tablename__ = "option_prices"
    __table_args__ = (
        UniqueConstraint("id", "option_version_id"), UniqueConstraint("option_version_id", "price_key"),
        ForeignKeyConstraint(["option_version_id", "knowledge_version_id"], ["application_option_versions.id", "application_option_versions.knowledge_version_id"]),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_price_nonnegative"),
        CheckConstraint("(target_scope = 'EXACT' AND target_tier_id IS NOT NULL) OR (target_scope = 'ALL_TARGETS' AND target_tier_id IS NULL)", name="ck_price_target_scope"),
        CheckConstraint("(known_state = 'KNOWN' AND amount IS NOT NULL AND (amount = 0 OR currency IS NOT NULL)) OR (known_state IN ('UNKNOWN','CONFLICT','NOT_APPLICABLE') AND amount IS NULL)", name="ck_price_known_state"),
        CheckConstraint("mapping_scope IN ('EXPLICIT','ALL_MAPPINGS')", name="ck_price_mapping_scope"),
        CheckConstraint("fee_role IN ('APPLICATION','CHALLENGE_SPEND','OTHER')", name="ck_price_role"),
        CheckConstraint("(combination='ALTERNATIVE' AND alternative_group IS NOT NULL) OR (combination IN ('REQUIRED','CONDITIONAL') AND alternative_group IS NULL)", name="ck_price_combination"),
        CheckConstraint("availability IN ('AVAILABLE','UNAVAILABLE','UNKNOWN','CONFLICT') AND (availability <> 'UNAVAILABLE' OR amount IS NULL)", name="ck_price_availability"),
        Index("ix_option_price_target", "option_version_id", "target_tier_id"),
    )
    option_version_id: Mapped[UUID] = mapped_column(Uuid)
    knowledge_version_id: Mapped[UUID] = mapped_column(Uuid)
    price_key: Mapped[str] = mapped_column(Text)
    target_tier_id: Mapped[UUID | None] = mapped_column(ForeignKey("membership_tiers.id"))
    target_scope: Mapped[str] = mapped_column(String(30))
    mapping_scope: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    known_state: Mapped[str] = mapped_column(String(30))
    fee_role: Mapped[str] = mapped_column(String(30))
    charge_key: Mapped[str] = mapped_column(Text)
    combination: Mapped[str] = mapped_column(String(30))
    alternative_group: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[dict] = mapped_column(J)
    raw_text: Mapped[str] = mapped_column(Text)
    availability: Mapped[str] = mapped_column(String(30))
    evidence_ids: Mapped[list] = mapped_column(J)


class OptionPriceMapping(Base):
    __tablename__ = "option_price_mappings"
    __table_args__ = (
        ForeignKeyConstraint(["price_id", "option_version_id"], ["option_prices.id", "option_prices.option_version_id"]),
        ForeignKeyConstraint(["mapping_id", "option_version_id"], ["option_mappings.id", "option_mappings.option_version_id"]),
    )
    price_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    mapping_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    option_version_id: Mapped[UUID] = mapped_column(Uuid)


class DocumentSection(Base, Identity):
    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("document_version_id", "section_key"), UniqueConstraint("id", "document_version_id"),
        ForeignKeyConstraint(["parent_id", "document_version_id"], ["document_sections.id", "document_sections.document_version_id"]),
        Index("ix_document_sections_order", "document_version_id", "ordinal"),
    )
    document_version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"))
    section_key: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(30))
    ordinal: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list] = mapped_column(J, default=list)
    body: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(J)
    related_section_ids: Mapped[list] = mapped_column(J, default=list)
    topics: Mapped[list] = mapped_column(J, default=list)


class ActivityDocument(Base, Identity):
    __tablename__ = "activity_documents"
    __table_args__ = (UniqueConstraint("knowledge_version_id", "document_version_id", "role"),
                      CheckConstraint("role IN ('OFFICIAL_PRIMARY','OFFICIAL_SUPPORT','THIRD_PARTY')", name="ck_activity_document_role"))
    knowledge_version_id: Mapped[UUID] = mapped_column(ForeignKey("activity_knowledge_versions.id"))
    document_version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"))
    role: Mapped[str] = mapped_column(String(30))
    section_scope: Mapped[list] = mapped_column(J, default=list)


class EvidenceReference(Base, Identity):
    __tablename__ = "evidence_references"
    __table_args__ = (
        ForeignKeyConstraint(["section_id", "document_version_id"], ["document_sections.id", "document_sections.document_version_id"]),
        UniqueConstraint("document_version_id", "content_hash"),
        CheckConstraint("(precision='SECTION' AND section_id IS NOT NULL) OR (precision='DOCUMENT_LEVEL' AND section_id IS NULL)", name="ck_evidence_precision"),
    )
    document_version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"))
    section_id: Mapped[UUID | None] = mapped_column(Uuid)
    precision: Mapped[str] = mapped_column(String(30))
    locator: Mapped[dict] = mapped_column(J)
    quote: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class ActivityBrief(Base, Identity):
    __tablename__ = "activity_briefs"
    __table_args__ = (UniqueConstraint("knowledge_version_id", "brief_kind", "generator_version"),)
    knowledge_version_id: Mapped[UUID] = mapped_column(ForeignKey("activity_knowledge_versions.id"))
    brief_kind: Mapped[str] = mapped_column(String(30))
    previous_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("activity_knowledge_versions.id"))
    generator_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    content: Mapped[dict] = mapped_column(J, default=dict)
    fact_refs: Mapped[list] = mapped_column(J, default=list)
    error_code: Mapped[str | None] = mapped_column(Text)


class ActivityObservationState(Base, TimestampMixin):
    __tablename__ = "activity_observation_state"
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    freshness: Mapped[str] = mapped_column(String(30), default="INCOMPLETE")


class KnowledgeMigrationLink(Base, Identity):
    __tablename__ = "knowledge_migration_links"
    __table_args__ = (UniqueConstraint("legacy_table", "legacy_id", "legacy_path", "migration_version"),)
    legacy_table: Mapped[str] = mapped_column(Text)
    legacy_id: Mapped[str] = mapped_column(Text)
    legacy_path: Mapped[str] = mapped_column(Text)
    target_table: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    migration_version: Mapped[str] = mapped_column(Text)
