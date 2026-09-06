from datetime import datetime, UTC
from journeyplus.knowledge.temporal import window_state


def known(**value):return {'known_state':'KNOWN','value':value}


def test_date_end_includes_whole_day_in_official_timezone():
    window={'start':known(precision='INSTANT',instant='2026-01-01T00:00:00Z'),
            'end':known(precision='DATE',date='2026-09-06',timezone='Asia/Shanghai')}
    assert window_state(window,datetime(2026,9,6,15,59,tzinfo=UTC))=='PASS'
    assert window_state(window,datetime(2026,9,6,16,tzinfo=UTC))=='ENDED'


def test_missing_or_invalid_timezone_and_relative_date_remain_unknown():
    for value in [dict(precision='DATE',date='2020-01-01'),
                  dict(precision='DATE',date='2020-01-01',timezone='Invalid/Zone'),
                  dict(precision='RELATIVE',offset_days=30,anchor='APPROVAL')]:
        assert window_state({'end':known(**value)},datetime.now(UTC))=='UNKNOWN'


def test_explicit_boundary_failure_dominates_other_unknowns():
    now=datetime(2026,9,6,8,tzinfo=UTC)
    assert window_state({'start':known(precision='INSTANT',instant='2026-09-06T09:00:00Z')},now)=='NOT_STARTED'
    assert window_state({'end':known(precision='INSTANT',instant='2026-09-06T07:00:00Z')},now)=='ENDED'
