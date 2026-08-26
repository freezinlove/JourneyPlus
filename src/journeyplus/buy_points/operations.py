from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.buy_points.parser import BUY_POINTS_PARSER_VERSION
from journeyplus.buy_points.service import (
    BUY_POINTS_SOURCE_ID,
    current_buy_points_snapshot,
    materialize_buy_points_snapshot,
)
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import BuyPointsSnapshotRecord, DocumentVersion, SourceItem


@dataclass(frozen=True, slots=True)
class BuyPointsDocumentResult:
    document_version_id: str
    snapshot_id: str | None
    offer_count: int
    reused: bool
    diagnostics: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BuyPointsProcessingSummary:
    selected: int
    attempted: int
    succeeded: int
    failed: int
    reused: int
    latest_offer_count: int
    diagnostics: tuple[str, ...]
    documents: tuple[BuyPointsDocumentResult, ...]


def pending_buy_points_documents(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    limit: int = 10,
) -> list[UUID]:
    if limit < 1:
        raise ValueError("limit must be positive")
    materialized = (
        select(BuyPointsSnapshotRecord.id)
        .where(
            BuyPointsSnapshotRecord.document_version_id == DocumentVersion.id,
            BuyPointsSnapshotRecord.parser_version == parser_version,
        )
        .correlate(DocumentVersion)
        .exists()
    )
    return list(
        session.scalars(
            select(DocumentVersion.id)
            .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
            .where(
                SourceItem.source_id == BUY_POINTS_SOURCE_ID,
                ~materialized,
            )
            .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
            .limit(limit)
        )
    )


def pending_buy_points_count(
    session: Session,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
) -> int:
    materialized = (
        select(BuyPointsSnapshotRecord.id)
        .where(
            BuyPointsSnapshotRecord.document_version_id == DocumentVersion.id,
            BuyPointsSnapshotRecord.parser_version == parser_version,
        )
        .correlate(DocumentVersion)
        .exists()
    )
    return int(
        session.scalar(
            select(func.count(DocumentVersion.id))
            .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
            .where(
                SourceItem.source_id == BUY_POINTS_SOURCE_ID,
                ~materialized,
            )
        )
        or 0
    )


def buy_points_job_key(
    document_version_id: UUID,
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
) -> str:
    return f"buy-points:{document_version_id}:{parser_version}"


def process_pending_buy_points(
    session_factory: sessionmaker[Session],
    *,
    parser_version: str = BUY_POINTS_PARSER_VERSION,
    limit: int = 10,
    max_attempts: int = 2,
) -> BuyPointsProcessingSummary:
    with session_factory() as session:
        selected = pending_buy_points_documents(
            session,
            parser_version=parser_version,
            limit=limit,
        )

    runner = JobRunner(session_factory, max_attempts=max_attempts)
    results: list[BuyPointsDocumentResult] = []
    for document_id in selected:

        def operation(
            current_document_id: UUID = document_id,
        ) -> BuyPointsDocumentResult:
            with session_factory.begin() as session:
                document = session.get(DocumentVersion, current_document_id)
                if document is None:
                    raise LookupError(
                        f"Document version {current_document_id} was not found"
                    )
                snapshot, reused = materialize_buy_points_snapshot(
                    session,
                    document,
                    parser_version=parser_version,
                )
                return BuyPointsDocumentResult(
                    document_version_id=str(current_document_id),
                    snapshot_id=str(snapshot.id),
                    offer_count=snapshot.parsed_offer_count,
                    reused=reused,
                    diagnostics=tuple(
                        str(item.get("code", "UNKNOWN"))
                        for item in snapshot.diagnostics
                    ),
                )

        try:
            result, skipped = runner.execute(
                idempotency_key=buy_points_job_key(
                    document_id, parser_version=parser_version
                ),
                job_type="buy_points_snapshot",
                operation=operation,
                serialize=asdict,
            )
            if skipped:
                results.append(
                    BuyPointsDocumentResult(
                        document_version_id=str(document_id),
                        snapshot_id=None,
                        offer_count=0,
                        reused=True,
                    )
                )
            elif result is not None:
                results.append(result)
        except Exception as exc:
            results.append(
                BuyPointsDocumentResult(
                    document_version_id=str(document_id),
                    snapshot_id=None,
                    offer_count=0,
                    reused=False,
                    error=_safe_error(exc),
                )
            )

    with session_factory() as session:
        latest = current_buy_points_snapshot(
            session, parser_version=parser_version
        )
    diagnostics = tuple(
        sorted(
            {
                diagnostic
                for result in results
                for diagnostic in result.diagnostics
            }
        )
    )
    return BuyPointsProcessingSummary(
        selected=len(selected),
        attempted=len(selected),
        succeeded=sum(item.error is None for item in results),
        failed=sum(item.error is not None for item in results),
        reused=sum(item.reused for item in results),
        latest_offer_count=latest.parsed_offer_count if latest else 0,
        diagnostics=diagnostics,
        documents=tuple(results),
    )


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {message}"[:1000]
