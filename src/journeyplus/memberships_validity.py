"""One inclusive calendar-date rule for all saved membership consumers."""
from datetime import datetime
from journeyplus.lifecycle.service import BEIJING_TZ


def membership_date(now=None):
    value = now or datetime.now(BEIJING_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ).date()


def is_active_membership(valid_until, *, today=None):
    return valid_until is None or valid_until >= (today or membership_date())
