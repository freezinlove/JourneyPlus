from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, HttpUrl

from journeyplus.contracts import StrictModel


class BuyPointsCategory(StrEnum):
    AIRLINE = "AIRLINE"
    HOTEL = "HOTEL"
    OTHER = "OTHER"


class BuyPointsOfferKind(StrEnum):
    BONUS = "BONUS"
    DISCOUNT = "DISCOUNT"


class BuyPointsDeadlineStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class BuyPointsDiffType(StrEnum):
    ADDED = "ADDED"
    CHANGED = "CHANGED"
    REMOVED = "REMOVED"
    UNCHANGED = "UNCHANGED"


class BuyPointsDiagnostic(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    blocking: bool = False


class BuyPointsEvidence(StrictModel):
    section_id: str = Field(min_length=1, max_length=200)
    program_text: str = Field(min_length=1, max_length=500)
    offer_text: str = Field(min_length=1, max_length=2000)
    deadline_text: str | None = Field(default=None, max_length=200)
    posting_time_text: str | None = Field(default=None, max_length=200)
    detail_href_raw: str | None = Field(default=None, max_length=2000)
    action_href_raw: str | None = Field(default=None, max_length=2000)


class ParsedBuyPointsOffer(StrictModel):
    offer_key: str = Field(min_length=1, max_length=500)
    category: BuyPointsCategory
    program_name: str = Field(min_length=1, max_length=500)
    offer_text: str = Field(min_length=1, max_length=2000)
    offer_kind: BuyPointsOfferKind
    max_percent: Decimal = Field(gt=0)
    deadline_raw: str | None = Field(default=None, max_length=200)
    deadline_date: date | None = None
    posting_time_raw: str | None = Field(default=None, max_length=200)
    detail_url: HttpUrl | None = None
    action_url: HttpUrl | None = None
    material_signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: BuyPointsEvidence


class ParsedBuyPointsPage(StrictModel):
    page_title: str = Field(min_length=1, max_length=1000)
    page_modified_at: datetime | None = None
    section_counts: dict[BuyPointsCategory, int]
    parsed_offer_count: int = Field(ge=0)
    offers_signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    diagnostics: list[BuyPointsDiagnostic] = Field(default_factory=list)
    offers: list[ParsedBuyPointsOffer]


class BuyPointsOfferView(StrictModel):
    snapshot_id: UUID
    document_version_id: UUID
    offer_key: str
    category: BuyPointsCategory
    program_name: str
    offer_kind: BuyPointsOfferKind
    max_percent: Decimal
    deadline_raw: str | None = None
    deadline_date: date | None = None
    posting_time_raw: str | None = None
    detail_url: str | None = None
    purchase_url: str | None = None
    material_signature: str
    is_currently_listed: bool
    deadline_status: BuyPointsDeadlineStatus
    source_stale: bool
    snapshot_created_at: datetime


class BuyPointsSnapshotView(StrictModel):
    snapshot_id: UUID
    document_version_id: UUID
    page_title: str
    page_modified_at: datetime | None = None
    parsed_offer_count: int
    offers_signature: str
    diagnostics: list[BuyPointsDiagnostic]
    created_at: datetime
    offers: list[BuyPointsOfferView]


class BuyPointsDiffItem(StrictModel):
    offer_key: str
    change_type: BuyPointsDiffType
    before: BuyPointsOfferView | None = None
    after: BuyPointsOfferView | None = None


class BuyPointsSnapshotDiff(StrictModel):
    before_snapshot_id: UUID
    after_snapshot_id: UUID
    items: list[BuyPointsDiffItem]
