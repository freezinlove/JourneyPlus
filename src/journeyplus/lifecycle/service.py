from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import FactSet, LifecycleStatus
from journeyplus.models import StatusEvent


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class LifecycleAdvanceSummary:
    scanned: int
    updated: int
    expired: int


def normalize_event_time(value: str | None, *, end_of_day: bool) -> datetime | None:
    """Normalize supported source time text to an aware Asia/Shanghai datetime."""

    if value is None or not value.strip():
        return None
    original = _strip_event_time_prefix(value.strip())
    named_zone_datetime = _parse_named_timezone_datetime(original)
    if named_zone_datetime is not None:
        return named_zone_datetime.astimezone(BEIJING_TZ)
    raw = _strip_beijing_suffix(original)
    parsed_date = _parse_date_only(raw)
    if parsed_date is not None:
        boundary = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, boundary, tzinfo=BEIJING_TZ)

    parsed_datetime = _parse_datetime(raw)
    if parsed_datetime is None:
        return None
    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=BEIJING_TZ)
    return parsed_datetime.astimezone(BEIJING_TZ)


def calculate_lifecycle(
    application_start_at: datetime | None,
    application_deadline_at: datetime | None,
    *,
    now: datetime | None = None,
) -> LifecycleStatus:
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    start = as_beijing(application_start_at) if application_start_at else None
    deadline = (
        as_beijing(application_deadline_at) if application_deadline_at else None
    )
    if deadline is None or (start is not None and start > deadline):
        return LifecycleStatus.UNKNOWN
    if start is not None and current < start:
        return LifecycleStatus.UPCOMING
    if current <= deadline:
        return LifecycleStatus.ACTIVE
    return LifecycleStatus.EXPIRED


def event_closed_for_automation(
    event: StatusEvent, *, now: datetime | None = None
) -> bool:
    from journeyplus.lifecycle.visibility import is_ended
    return is_ended(event, now=now)


def windows_non_overlapping(
    left_start: datetime | None,
    left_deadline: datetime | None,
    right_start: datetime | None,
    right_deadline: datetime | None,
) -> bool:
    left_start = as_beijing(left_start) if left_start else None
    left_deadline = as_beijing(left_deadline) if left_deadline else None
    right_start = as_beijing(right_start) if right_start else None
    right_deadline = as_beijing(right_deadline) if right_deadline else None
    return bool(
        (left_start and right_deadline and left_start > right_deadline)
        or (right_start and left_deadline and right_start > left_deadline)
    )


def refresh_event_lifecycle(
    event: StatusEvent,
    fact_set: FactSet,
    *,
    now: datetime | None = None,
    allow_manual_restore: bool = False,
) -> LifecycleStatus:
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    start_field = fact_set.application_start
    deadline_field = fact_set.deadline
    event.application_start_at = (
        normalize_event_time(start_field.value, end_of_day=False)
        if not start_field.conflict
        else None
    )
    event.application_deadline_at = (
        normalize_event_time(deadline_field.value, end_of_day=True)
        if not deadline_field.conflict
        else None
    )
    lifecycle = calculate_lifecycle(
        event.application_start_at,
        event.application_deadline_at,
        now=current,
    )
    if event.archived_at is not None and not allow_manual_restore:
        event.lifecycle_status = LifecycleStatus.EXPIRED
        return LifecycleStatus.EXPIRED
    event.lifecycle_status = lifecycle
    if lifecycle == LifecycleStatus.EXPIRED:
        event.archived_at = event.archived_at or current
    elif allow_manual_restore and event.archived_at is not None:
        event.archived_at = None
    return lifecycle


def advance_lifecycles(
    session: Session, *, now: datetime | None = None
) -> LifecycleAdvanceSummary:
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    events = list(
        session.scalars(
            select(StatusEvent).where(StatusEvent.merged_into_id.is_(None))
        )
    )
    updated = 0
    expired = 0
    for event in events:
        before = (event.lifecycle_status, event.archived_at)
        lifecycle = (
            LifecycleStatus.EXPIRED
            if event.archived_at is not None or event.lifecycle_status == LifecycleStatus.EXPIRED
            else calculate_lifecycle(
                event.application_start_at,
                event.application_deadline_at,
                now=current,
            )
        )
        event.lifecycle_status = lifecycle
        if lifecycle == LifecycleStatus.EXPIRED:
            expired += 1
            event.archived_at = event.archived_at or current
        if before != (event.lifecycle_status, event.archived_at):
            updated += 1
    session.flush()
    return LifecycleAdvanceSummary(len(events), updated, expired)


def as_beijing(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)


def _strip_beijing_suffix(value: str) -> str:
    return re.sub(
        r"\s*(?:北京时间|中国标准时间|Asia/Shanghai|CST)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _strip_event_time_prefix(value: str) -> str:
    return re.sub(
        r"^(?:(?:register|apply|enroll|enrol|sign\s+up)\s+"
        r"(?:by|before|through|until)|(?:registration|application)\s+"
        r"(?:deadline|ends?)|deadline)\s*(?:is|:)?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _parse_date_only(value: str) -> date | None:
    for pattern in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%m/%d/%y",
        "%m-%d-%y",
        "%Y年%m月%d日",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d, %y",
        "%b %d, %y",
        "%d %B %Y",
        "%d %b %Y",
        "%d %B %y",
        "%d %b %y",
    ):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: str) -> datetime | None:
    iso_value = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
        "%B %d, %Y %H:%M",
        "%b %d, %Y %H:%M",
    ):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


_FIXED_ZONE_OFFSETS = {
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
}

_REGIONAL_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}

_TIME_WITH_ZONE_FIRST = re.compile(
    r"^(?P<clock>\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))"
    r"\s*(?P<zone>EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT)"
    r"\s+on\s+(?P<day>.+)$",
    re.IGNORECASE,
)

_DATE_WITH_ZONE_LAST = re.compile(
    r"^(?P<day>.+?)\s+(?:at\s+)?"
    r"(?P<clock>\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))"
    r"\s*(?P<zone>EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT)$",
    re.IGNORECASE,
)


def _parse_named_timezone_datetime(value: str) -> datetime | None:
    match = _TIME_WITH_ZONE_FIRST.fullmatch(value) or _DATE_WITH_ZONE_LAST.fullmatch(
        value
    )
    if match is None:
        return None
    parsed_day = _parse_date_only(match.group("day").strip().rstrip(",").strip())
    parsed_clock = _parse_clock(match.group("clock"))
    zone = _named_timezone(match.group("zone"), parsed_day)
    if parsed_day is None or parsed_clock is None or zone is None:
        return None
    return datetime.combine(parsed_day, parsed_clock, tzinfo=zone)


def _parse_clock(value: str) -> time | None:
    normalized = re.sub(r"\.", "", value).upper()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for pattern in ("%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(normalized, pattern).time()
        except ValueError:
            continue
    return None


def _named_timezone(value: str, parsed_day: date | None) -> tzinfo | None:
    if parsed_day is None:
        return None
    abbreviation = value.upper()
    offset = _FIXED_ZONE_OFFSETS.get(abbreviation)
    if offset is not None:
        return timezone(timedelta(hours=offset), name=abbreviation)
    zone_name = _REGIONAL_ZONES.get(abbreviation)
    return ZoneInfo(zone_name) if zone_name is not None else None
