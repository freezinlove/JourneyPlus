from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from journeyplus.buy_points.contracts import (
    BuyPointsDeadlineStatus,
    BuyPointsDiffType,
)
from journeyplus.buy_points.operations import (
    pending_buy_points_count,
    pending_buy_points_documents,
    process_pending_buy_points,
)
from journeyplus.buy_points.parser import BUY_POINTS_PARSER_VERSION
from journeyplus.buy_points.service import (
    adjacent_buy_points_snapshot_diff,
    buy_points_offer_history,
    buy_points_snapshot_history,
    current_buy_points_snapshot,
    diff_buy_points_snapshots,
    materialize_buy_points_snapshot,
)
from journeyplus.models import (
    ArticleOpportunityRecord,
    BriefRecord,
    BuyPointsOfferRecord,
    BuyPointsSnapshotRecord,
    DocumentVersion,
    FactSetRecord,
    JobRun,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str = "awardwallet_buy_points.html") -> str:
    return (FIXTURES / name).read_text()


def _add_document(session, raw_html: str) -> DocumentVersion:
    item = session.scalar(
        select(SourceItem).where(
            SourceItem.source_id == "awardwallet_buy_points_page"
        )
    )
    if item is None:
        item = SourceItem(
            source_id="awardwallet_buy_points_page",
            external_id="current-promotions-buy-points-miles",
            discovered_url=(
                "https://awardwallet.com/news/"
                "current-promotions-buy-points-miles/"
            ),
            canonical_url=(
                "https://awardwallet.com/news/"
                "current-promotions-buy-points-miles/"
            ),
            title="Current Promotions",
            observed_at=datetime.now(UTC),
            raw_metadata={"refresh_on_discovery": True},
        )
        session.add(item)
        session.flush()
    digest = hashlib.sha256(raw_html.encode()).hexdigest()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=item.canonical_url,
        raw_body=raw_html,
        normalized_body=raw_html,
        content_type="text/html",
        storage_mode="inline_raw_and_normalized",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="html-v2",
        fetched_at=datetime.now(UTC),
    )
    session.add(document)
    session.flush()
    return document


def test_snapshot_materialization_is_immutable_idempotent_and_versioned(
    db_session,
) -> None:
    seed_sources(db_session)
    document = _add_document(db_session, _fixture())

    first, first_reused = materialize_buy_points_snapshot(db_session, document)
    repeated, repeated_reused = materialize_buy_points_snapshot(db_session, document)
    upgraded, upgraded_reused = materialize_buy_points_snapshot(
        db_session,
        document,
        parser_version="awardwallet-buy-points-v2",
    )

    assert first_reused is upgraded_reused is False
    assert repeated_reused is True and repeated.id == first.id
    assert upgraded.id != first.id
    assert db_session.scalar(select(func.count()).select_from(BuyPointsSnapshotRecord)) == 2
    assert db_session.scalar(select(func.count()).select_from(BuyPointsOfferRecord)) == 8
    assert first.offers_signature == upgraded.offers_signature


def test_current_history_deadline_state_and_structured_diff(db_session) -> None:
    seed_sources(db_session)
    first_document = _add_document(db_session, _fixture())
    first, _ = materialize_buy_points_snapshot(db_session, first_document)
    changed_html = _fixture().replace("8/26/26", "9/26/26", 1)
    second_document = _add_document(db_session, changed_html)
    second, _ = materialize_buy_points_snapshot(db_session, second_document)

    current = current_buy_points_snapshot(
        db_session,
        as_of=datetime(2026, 8, 27).date(),
    )
    history = buy_points_snapshot_history(db_session, limit=10)
    diff = diff_buy_points_snapshots(
        db_session,
        first.id,
        second.id,
        as_of=datetime(2026, 8, 27).date(),
    )
    adjacent = adjacent_buy_points_snapshot_diff(db_session)

    assert current is not None and current.snapshot_id == second.id
    assert len(history) == 2
    southwest = next(
        item for item in current.offers if item.program_name.startswith("Southwest")
    )
    virgin = next(
        item for item in current.offers if item.program_name.startswith("Virgin")
    )
    offer_history = buy_points_offer_history(
        db_session, southwest.offer_key, limit=10
    )
    assert len(offer_history) == 2
    assert {item.offer_key for item in offer_history} == {southwest.offer_key}
    assert southwest.deadline_status == BuyPointsDeadlineStatus.ACTIVE
    assert southwest.is_currently_listed is True
    assert virgin.deadline_status == BuyPointsDeadlineStatus.UNKNOWN
    assert sum(item.change_type == BuyPointsDiffType.CHANGED for item in diff.items) == 1
    assert sum(item.change_type == BuyPointsDiffType.UNCHANGED for item in diff.items) == 3
    assert adjacent is not None
    assert adjacent.before_snapshot_id == first.id
    assert adjacent.after_snapshot_id == second.id


def test_expired_but_listed_offer_has_separate_staleness_diagnostic(db_session) -> None:
    seed_sources(db_session)
    document = _add_document(db_session, _fixture())
    materialize_buy_points_snapshot(db_session, document)

    current = current_buy_points_snapshot(
        db_session,
        as_of=datetime(2026, 8, 27).date(),
    )

    assert current is not None
    southwest = next(
        item for item in current.offers if item.program_name.startswith("Southwest")
    )
    assert southwest.is_currently_listed is True
    assert southwest.deadline_status == BuyPointsDeadlineStatus.EXPIRED
    assert southwest.source_stale is True
    assert "SOURCE_LISTS_EXPIRED_OFFERS" in {
        item.code for item in current.diagnostics
    }


def test_zero_snapshot_produces_removed_and_reverse_added_diff(db_session) -> None:
    seed_sources(db_session)
    full_document = _add_document(db_session, _fixture())
    full, _ = materialize_buy_points_snapshot(db_session, full_document)
    zero_document = _add_document(
        db_session, _fixture("awardwallet_buy_points_zero.html")
    )
    zero, _ = materialize_buy_points_snapshot(db_session, zero_document)

    removed = diff_buy_points_snapshots(db_session, full.id, zero.id)
    added = diff_buy_points_snapshots(db_session, zero.id, full.id)

    assert len(removed.items) == 4
    assert {item.change_type for item in removed.items} == {
        BuyPointsDiffType.REMOVED
    }
    assert {item.change_type for item in added.items} == {
        BuyPointsDiffType.ADDED
    }


def test_pending_processing_is_source_scoped_zero_ai_and_preserves_old_view(
    session_factory,
) -> None:
    invalid = _fixture().replace("4 Current", "99 Current", 1)
    with session_factory.begin() as session:
        seed_sources(session)
        good_document = _add_document(session, _fixture())
    first = process_pending_buy_points(session_factory)
    with session_factory.begin() as session:
        bad_document = _add_document(session, invalid)
        assert pending_buy_points_count(session) == 1
        assert pending_buy_points_documents(session) == [bad_document.id]

    failed = process_pending_buy_points(session_factory)
    rerun = process_pending_buy_points(session_factory)

    assert first.selected == first.succeeded == 1
    assert first.latest_offer_count == 4
    assert failed.selected == failed.failed == 1
    assert rerun.selected == rerun.failed == 1
    with session_factory() as session:
        current = current_buy_points_snapshot(session)
        run = session.scalar(
            select(JobRun).where(
                JobRun.idempotency_key.contains(str(bad_document.id))
            )
        )
        assert current is not None
        assert current.document_version_id == good_document.id
        assert run is not None and run.status == "FAILED" and run.attempts == 2
        assert run.error is not None and "<html" not in run.error
        assert session.scalar(select(func.count()).select_from(StatusEvent)) == 0
        assert session.scalar(
            select(func.count()).select_from(ArticleOpportunityRecord)
        ) == 0
        assert session.scalar(select(func.count()).select_from(FactSetRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 0


def test_pending_query_does_not_select_other_sources(db_session) -> None:
    seed_sources(db_session)
    _add_document(db_session, _fixture())
    other_item = SourceItem(
        source_id="loyaltylobby_feed",
        external_id="unrelated",
        discovered_url="https://loyaltylobby.com/unrelated",
        canonical_url="https://loyaltylobby.com/unrelated",
        title="Unrelated",
        observed_at=datetime.now(UTC),
        raw_metadata={},
    )
    db_session.add(other_item)
    db_session.flush()
    db_session.add(
        DocumentVersion(
            source_item_id=other_item.id,
            canonical_url=other_item.canonical_url,
            raw_body="<article>unrelated</article>",
            normalized_body="unrelated",
            content_type="text/html",
            storage_mode="inline_raw_and_normalized",
            raw_hash="a" * 64,
            normalized_hash="b" * 64,
            parser_version="html-v2",
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    selected = pending_buy_points_documents(db_session)

    assert len(selected) == 1
    assert pending_buy_points_count(
        db_session, parser_version=BUY_POINTS_PARSER_VERSION
    ) == 1
