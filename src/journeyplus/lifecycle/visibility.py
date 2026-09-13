"""Read-time lifecycle for the existing workflow records; never mutates facts."""
from datetime import datetime
from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing, calculate_lifecycle


def effective_status(record, *, now=None):
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    article = hasattr(record, 'visibility_until_at')
    lifecycle = calculate_lifecycle(record.application_start_at, record.application_deadline_at, now=current)
    if not article:
        if record.archived_at is not None or record.lifecycle_status == 'EXPIRED':
            return 'EXPIRED'
        return str(lifecycle)
    if lifecycle == 'EXPIRED' or record.archive_reason == 'DEADLINE_EXPIRED':
        return 'EXPIRED'
    if record.archived_at is not None:
        return 'STALE' if record.archive_reason == 'STALE_180D' else 'ARCHIVED'
    if (record.visibility_until_at is not None
            and current >= as_beijing(record.visibility_until_at)):
        # An explicit deadline includes its final instant; freshness windows do not.
        if record.visibility_policy == 'DEFAULT_180_DAYS':
            return 'STALE'
        if record.visibility_policy == 'EXPLICIT_DEADLINE':
            if record.application_deadline_at is None and current > as_beijing(record.visibility_until_at):
                return 'EXPIRED'
        else:
            return 'ARCHIVED'
    return str(lifecycle)


def is_ended(record, *, now=None):
    return effective_status(record, now=now) in {'EXPIRED', 'STALE', 'ARCHIVED'}


def contributes(record, *, now=None):
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    return (not is_ended(record, now=current)
            and not getattr(record, 'merged_into_id', None)
            and (record.application_start_at is None or current >= as_beijing(record.application_start_at))
            and (not hasattr(record, 'visibility_until_at') or record.visibility_until_at is not None))
