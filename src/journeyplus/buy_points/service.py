from __future__ import annotations

from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.buy_points.contracts import (
    BuyPointsDeadlineStatus,
    BuyPointsDiagnostic,
    BuyPointsDiffItem,
    BuyPointsDiffType,
    BuyPointsEvidence,
    BuyPointsOfferView,
    BuyPointsSnapshotDiff,
    BuyPointsSnapshotView,
)
from journeyplus.buy_points.parser import (
    BUY_POINTS_PARSER_VERSION,
    parse_awardwallet_buy_points,
)
from journeyplus.models import (
    BuyPointsOfferRecord,
    BuyPointsSnapshotRecord,
    DocumentVersion,
    SourceItem,
)


BUY_POINTS_SOURCE_ID = "awardwallet_buy_points_page"
BEIJING = ZoneInfo("Asia/Shanghai")


def materialize_buy_points_snapshot(
    session: Session,
    document: DocumentVersion,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
) -> tuple[BuyPointsSnapshotRecord, bool]:
    existing = session.scalar(
        select(BuyPointsSnapshotRecord).where(
            BuyPointsSnapshotRecord.document_version_id == document.id,
            BuyPointsSnapshotRecord.parser_version == parser_version,
        )
    )
    if existing is not None:
        return existing, True

    item = session.get(SourceItem, document.source_item_id)
    if item is None or item.source_id != BUY_POINTS_SOURCE_ID:
        raise ValueError(
            "Buy-points snapshots can only be materialized from the configured "
            "AwardWallet source"
        )
    if document.raw_body is None:
        raise ValueError("Buy-points parsing requires the stored raw HTML body")

    parsed = parse_awardwallet_buy_points(
        document.raw_body,
        page_url=document.canonical_url,
    )
    snapshot = BuyPointsSnapshotRecord(
        source_item_id=item.id,
        document_version_id=document.id,
        parser_version=parser_version,
        page_title=parsed.page_title,
        page_modified_at=parsed.page_modified_at,
        advertised_offer_count=parsed.advertised_offer_count,
        parsed_offer_count=parsed.parsed_offer_count,
        offers_signature=parsed.offers_signature,
        diagnostics=[item.model_dump(mode="json") for item in parsed.diagnostics],
    )
    session.add(snapshot)
    session.flush()
    for offer in parsed.offers:
        session.add(
            BuyPointsOfferRecord(
                snapshot_id=snapshot.id,
                offer_key=offer.offer_key,
                category=offer.category.value,
                program_name=offer.program_name,
                offer_text=offer.offer_text,
                offer_kind=offer.offer_kind.value,
                max_percent=offer.max_percent,
                purchase_rate_raw=offer.purchase_rate_raw,
                purchase_rate_cents=offer.purchase_rate_cents,
                deadline_raw=offer.deadline_raw,
                deadline_date=offer.deadline_date,
                posting_time_raw=offer.posting_time_raw,
                detail_url=str(offer.detail_url) if offer.detail_url else None,
                action_url=str(offer.action_url) if offer.action_url else None,
                top_pick=offer.top_pick,
                material_signature=offer.material_signature,
                evidence=offer.evidence.model_dump(mode="json"),
            )
        )
    session.flush()
    return snapshot, False


def latest_buy_points_snapshot_record(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
) -> BuyPointsSnapshotRecord | None:
    return session.scalar(
        select(BuyPointsSnapshotRecord)
        .join(SourceItem, SourceItem.id == BuyPointsSnapshotRecord.source_item_id)
        .where(
            SourceItem.source_id == BUY_POINTS_SOURCE_ID,
            BuyPointsSnapshotRecord.parser_version == parser_version,
        )
        .order_by(
            BuyPointsSnapshotRecord.created_at.desc(),
            BuyPointsSnapshotRecord.id.desc(),
        )
        .limit(1)
    )


def current_buy_points_snapshot(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    as_of: date | None = None,
) -> BuyPointsSnapshotView | None:
    snapshot = latest_buy_points_snapshot_record(
        session, parser_version=parser_version
    )
    if snapshot is None:
        return None
    offers = _snapshot_offer_records(session, snapshot.id)
    return _snapshot_view(
        snapshot,
        offers,
        currently_listed_keys={item.offer_key for item in offers},
        as_of=as_of,
    )


def buy_points_snapshot_history(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    offer_key: str | None = None,
    limit: int = 20,
    as_of: date | None = None,
) -> list[BuyPointsSnapshotView]:
    if limit < 1:
        raise ValueError("limit must be positive")
    statement = (
        select(BuyPointsSnapshotRecord)
        .join(SourceItem, SourceItem.id == BuyPointsSnapshotRecord.source_item_id)
        .where(
            SourceItem.source_id == BUY_POINTS_SOURCE_ID,
            BuyPointsSnapshotRecord.parser_version == parser_version,
        )
        .order_by(
            BuyPointsSnapshotRecord.created_at.desc(),
            BuyPointsSnapshotRecord.id.desc(),
        )
        .limit(limit)
    )
    if offer_key is not None:
        statement = statement.join(
            BuyPointsOfferRecord,
            BuyPointsOfferRecord.snapshot_id == BuyPointsSnapshotRecord.id,
        ).where(BuyPointsOfferRecord.offer_key == offer_key)
    snapshots = list(session.scalars(statement))
    current = latest_buy_points_snapshot_record(
        session, parser_version=parser_version
    )
    current_keys = (
        {
            item.offer_key
            for item in _snapshot_offer_records(session, current.id)
        }
        if current is not None
        else set()
    )
    return [
        _snapshot_view(
            snapshot,
            _snapshot_offer_records(session, snapshot.id),
            currently_listed_keys=current_keys,
            as_of=as_of,
        )
        for snapshot in snapshots
    ]


def buy_points_offer_history(
    session: Session,
    offer_key: str,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    limit: int = 20,
    as_of: date | None = None,
) -> list[BuyPointsOfferView]:
    if not offer_key.strip():
        raise ValueError("offer_key must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = list(
        session.execute(
            select(BuyPointsOfferRecord, BuyPointsSnapshotRecord)
            .join(
                BuyPointsSnapshotRecord,
                BuyPointsSnapshotRecord.id == BuyPointsOfferRecord.snapshot_id,
            )
            .join(
                SourceItem,
                SourceItem.id == BuyPointsSnapshotRecord.source_item_id,
            )
            .where(
                SourceItem.source_id == BUY_POINTS_SOURCE_ID,
                BuyPointsSnapshotRecord.parser_version == parser_version,
                BuyPointsOfferRecord.offer_key == offer_key,
            )
            .order_by(
                BuyPointsSnapshotRecord.created_at.desc(),
                BuyPointsSnapshotRecord.id.desc(),
            )
            .limit(limit)
        )
    )
    current = latest_buy_points_snapshot_record(
        session, parser_version=parser_version
    )
    current_keys = (
        {
            item.offer_key
            for item in _snapshot_offer_records(session, current.id)
        }
        if current is not None
        else set()
    )
    return [
        _offer_view(
            offer,
            snapshot,
            is_currently_listed=offer.offer_key in current_keys,
            as_of=as_of,
        )
        for offer, snapshot in rows
    ]


def diff_buy_points_snapshots(
    session: Session,
    before_snapshot_id: UUID,
    after_snapshot_id: UUID,
    *,
    as_of: date | None = None,
) -> BuyPointsSnapshotDiff:
    before_snapshot = session.get(BuyPointsSnapshotRecord, before_snapshot_id)
    after_snapshot = session.get(BuyPointsSnapshotRecord, after_snapshot_id)
    if before_snapshot is None or after_snapshot is None:
        raise LookupError("Both buy-points snapshots must exist")
    if before_snapshot.parser_version != after_snapshot.parser_version:
        raise ValueError("Snapshot diff requires the same parser version")
    before_records = {
        item.offer_key: item
        for item in _snapshot_offer_records(session, before_snapshot.id)
    }
    after_records = {
        item.offer_key: item
        for item in _snapshot_offer_records(session, after_snapshot.id)
    }
    after_keys = set(after_records)
    items: list[BuyPointsDiffItem] = []
    for offer_key in sorted(set(before_records) | set(after_records)):
        before_record = before_records.get(offer_key)
        after_record = after_records.get(offer_key)
        if before_record is None:
            change_type = BuyPointsDiffType.ADDED
        elif after_record is None:
            change_type = BuyPointsDiffType.REMOVED
        elif before_record.material_signature != after_record.material_signature:
            change_type = BuyPointsDiffType.CHANGED
        else:
            change_type = BuyPointsDiffType.UNCHANGED
        items.append(
            BuyPointsDiffItem(
                offer_key=offer_key,
                change_type=change_type,
                before=(
                    _offer_view(
                        before_record,
                        before_snapshot,
                        is_currently_listed=offer_key in after_keys,
                        as_of=as_of,
                    )
                    if before_record is not None
                    else None
                ),
                after=(
                    _offer_view(
                        after_record,
                        after_snapshot,
                        is_currently_listed=True,
                        as_of=as_of,
                    )
                    if after_record is not None
                    else None
                ),
            )
        )
    return BuyPointsSnapshotDiff(
        before_snapshot_id=before_snapshot.id,
        after_snapshot_id=after_snapshot.id,
        items=items,
    )


def adjacent_buy_points_snapshot_diff(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    as_of: date | None = None,
) -> BuyPointsSnapshotDiff | None:
    snapshots = list(
        session.scalars(
            select(BuyPointsSnapshotRecord)
            .join(
                SourceItem,
                SourceItem.id == BuyPointsSnapshotRecord.source_item_id,
            )
            .where(
                SourceItem.source_id == BUY_POINTS_SOURCE_ID,
                BuyPointsSnapshotRecord.parser_version == parser_version,
            )
            .order_by(
                BuyPointsSnapshotRecord.created_at.desc(),
                BuyPointsSnapshotRecord.id.desc(),
            )
            .limit(2)
        )
    )
    if len(snapshots) < 2:
        return None
    return diff_buy_points_snapshots(
        session,
        snapshots[1].id,
        snapshots[0].id,
        as_of=as_of,
    )


def _snapshot_offer_records(
    session: Session, snapshot_id: UUID
) -> list[BuyPointsOfferRecord]:
    return list(
        session.scalars(
            select(BuyPointsOfferRecord)
            .where(BuyPointsOfferRecord.snapshot_id == snapshot_id)
            .order_by(BuyPointsOfferRecord.category, BuyPointsOfferRecord.offer_key)
        )
    )


def _snapshot_view(
    snapshot: BuyPointsSnapshotRecord,
    offers: list[BuyPointsOfferRecord],
    *,
    currently_listed_keys: set[str],
    as_of: date | None,
) -> BuyPointsSnapshotView:
    offer_views = [
        _offer_view(
            item,
            snapshot,
            is_currently_listed=item.offer_key in currently_listed_keys,
            as_of=as_of,
        )
        for item in offers
    ]
    diagnostics = [
        BuyPointsDiagnostic.model_validate(item) for item in snapshot.diagnostics
    ]
    stale_count = sum(item.source_stale for item in offer_views)
    if stale_count:
        diagnostics.append(
            BuyPointsDiagnostic(
                code="SOURCE_LISTS_EXPIRED_OFFERS",
                message=(
                    f"The source still lists {stale_count} offer(s) whose deadline "
                    "has passed in Asia/Shanghai."
                ),
            )
        )
    return BuyPointsSnapshotView(
        snapshot_id=snapshot.id,
        document_version_id=snapshot.document_version_id,
        page_title=snapshot.page_title,
        page_modified_at=snapshot.page_modified_at,
        advertised_offer_count=snapshot.advertised_offer_count,
        parsed_offer_count=snapshot.parsed_offer_count,
        offers_signature=snapshot.offers_signature,
        diagnostics=diagnostics,
        created_at=snapshot.created_at,
        offers=offer_views,
    )


def _offer_view(
    offer: BuyPointsOfferRecord,
    snapshot: BuyPointsSnapshotRecord,
    *,
    is_currently_listed: bool,
    as_of: date | None,
) -> BuyPointsOfferView:
    current_day = as_of or date.today()
    if as_of is None:
        from datetime import datetime

        current_day = datetime.now(BEIJING).date()
    if offer.deadline_date is None:
        deadline_status = BuyPointsDeadlineStatus.UNKNOWN
    elif offer.deadline_date < current_day:
        deadline_status = BuyPointsDeadlineStatus.EXPIRED
    else:
        deadline_status = BuyPointsDeadlineStatus.ACTIVE
    return BuyPointsOfferView(
        snapshot_id=snapshot.id,
        document_version_id=snapshot.document_version_id,
        offer_key=offer.offer_key,
        category=offer.category,
        program_name=offer.program_name,
        offer_text=offer.offer_text,
        offer_kind=offer.offer_kind,
        max_percent=offer.max_percent,
        purchase_rate_raw=offer.purchase_rate_raw,
        purchase_rate_cents=offer.purchase_rate_cents,
        deadline_raw=offer.deadline_raw,
        deadline_date=offer.deadline_date,
        posting_time_raw=offer.posting_time_raw,
        detail_url=offer.detail_url,
        action_url=offer.action_url,
        top_pick=offer.top_pick,
        material_signature=offer.material_signature,
        evidence=BuyPointsEvidence.model_validate(offer.evidence),
        is_currently_listed=is_currently_listed,
        deadline_status=deadline_status,
        source_stale=(
            is_currently_listed
            and deadline_status == BuyPointsDeadlineStatus.EXPIRED
        ),
        snapshot_created_at=snapshot.created_at,
    )
