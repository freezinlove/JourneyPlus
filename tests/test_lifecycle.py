from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from journeyplus.contracts import LifecycleStatus
from journeyplus.lifecycle.service import (
    advance_lifecycles,
    calculate_lifecycle,
    normalize_event_time,
)
from journeyplus.models import StatusEvent


BEIJING = ZoneInfo("Asia/Shanghai")


def _event(key: str, *, start=None, deadline=None) -> StatusEvent:
    return StatusEvent(
        created_from_key=key,
        program="Example Air",
        target_status="Gold",
        summary="Status match",
        search_text="Example Air status match Gold",
        application_start_at=start,
        application_deadline_at=deadline,
    )


def test_date_only_boundaries_and_offset_times_normalize_to_beijing() -> None:
    start = normalize_event_time("2026-09-01", end_of_day=False)
    deadline = normalize_event_time("2026-09-01", end_of_day=True)
    converted = normalize_event_time(
        "2026-09-01T16:00:00+00:00", end_of_day=False
    )
    naive = normalize_event_time("2026-09-01 12:30", end_of_day=False)

    assert start == datetime(2026, 9, 1, 0, 0, tzinfo=BEIJING)
    assert deadline == datetime(
        2026, 9, 1, 23, 59, 59, 999999, tzinfo=BEIJING
    )
    assert converted == datetime(2026, 9, 2, 0, 0, tzinfo=BEIJING)
    assert naive == datetime(2026, 9, 1, 12, 30, tzinfo=BEIJING)
    assert normalize_event_time("sometime soon", end_of_day=True) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9/30/26", datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=BEIJING)),
        ("Jun 30, 25", datetime(2025, 6, 30, 23, 59, 59, 999999, tzinfo=BEIJING)),
        ("Dec 31, 25", datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=BEIJING)),
    ],
)
def test_real_article_two_digit_year_dates_normalize_to_beijing(
    raw: str, expected: datetime
) -> None:
    assert normalize_event_time(raw, end_of_day=True) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "11:59 p.m. EST on May 28, 2026",
            datetime(2026, 5, 29, 12, 59, tzinfo=BEIJING),
        ),
        (
            "June 30, 2025 at 11:59 p.m. CT",
            datetime(2025, 7, 1, 12, 59, tzinfo=BEIJING),
        ),
        (
            "May 28, 2026 11:59 p.m. EDT",
            datetime(2026, 5, 29, 11, 59, tzinfo=BEIJING),
        ),
        (
            "May 28, 2026, 11:59 p.m. EST",
            datetime(2026, 5, 29, 12, 59, tzinfo=BEIJING),
        ),
    ],
)
def test_real_article_named_us_timezones_convert_to_beijing(
    raw: str, expected: datetime
) -> None:
    assert normalize_event_time(raw, end_of_day=True) == expected


@pytest.mark.parametrize(
    ("start", "deadline", "expected"),
    [
        (None, None, LifecycleStatus.UNKNOWN),
        (
            datetime(2026, 2, 1, tzinfo=BEIJING),
            None,
            LifecycleStatus.UNKNOWN,
        ),
        (
            datetime(2026, 2, 1, tzinfo=BEIJING),
            datetime(2026, 2, 28, tzinfo=BEIJING),
            LifecycleStatus.UPCOMING,
        ),
        (
            datetime(2026, 1, 1, tzinfo=BEIJING),
            datetime(2026, 1, 31, tzinfo=BEIJING),
            LifecycleStatus.ACTIVE,
        ),
        (
            datetime(2025, 12, 1, tzinfo=BEIJING),
            datetime(2025, 12, 31, tzinfo=BEIJING),
            LifecycleStatus.EXPIRED,
        ),
        (
            datetime(2026, 3, 1, tzinfo=BEIJING),
            datetime(2026, 2, 1, tzinfo=BEIJING),
            LifecycleStatus.UNKNOWN,
        ),
    ],
)
def test_lifecycle_matrix_is_deterministic(start, deadline, expected) -> None:
    assert (
        calculate_lifecycle(
            start,
            deadline,
            now=datetime(2026, 1, 15, 12, 0, tzinfo=BEIJING),
        )
        == expected
    )


def test_lifecycle_advance_soft_archives_without_deleting_history(db_session) -> None:
    expired = _event(
        "expired",
        deadline=datetime(2026, 1, 1, 23, 59, 59, tzinfo=BEIJING),
    )
    active = _event(
        "active",
        deadline=datetime(2026, 1, 31, 23, 59, 59, tzinfo=BEIJING),
    )
    unknown = _event("unknown")
    db_session.add_all([expired, active, unknown])
    db_session.flush()
    now = datetime(2026, 1, 15, 12, 0, tzinfo=BEIJING)

    first = advance_lifecycles(db_session, now=now)
    archived_at = expired.archived_at
    second = advance_lifecycles(db_session, now=now)

    assert first.scanned == 3 and first.expired == 1 and first.updated == 2
    assert second.scanned == 3 and second.updated == 0
    assert expired.lifecycle_status == LifecycleStatus.EXPIRED
    assert expired.archived_at == archived_at == now
    assert active.lifecycle_status == LifecycleStatus.ACTIVE
    assert active.archived_at is None
    assert unknown.lifecycle_status == LifecycleStatus.UNKNOWN
    assert db_session.scalar(select(func.count()).select_from(StatusEvent)) == 3
