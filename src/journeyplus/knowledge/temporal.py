"""Conservative application-window evaluation without inventing a timezone."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def window_state(window, now):
    states=[]
    for side in ('start','end'):
        fact=window.get(side,{})
        if fact.get('known_state')!='KNOWN':
            states.append('UNKNOWN')
            continue
        value=fact.get('value') or {}
        try:
            if value.get('precision')=='INSTANT':
                boundary=datetime.fromisoformat(value['instant'])
                if boundary.tzinfo is None:raise ValueError('Missing timezone')
            elif value.get('precision')=='DATE' and value.get('timezone'):
                boundary=datetime.combine(datetime.fromisoformat(value['date']).date(),time(),ZoneInfo(value['timezone']))
                if side=='end':boundary+=timedelta(days=1)
            else:
                states.append('UNKNOWN');continue
            if side=='start' and now<boundary:states.append('NOT_STARTED')
            elif side=='end' and (now>=boundary if value.get('precision')=='DATE' else now>boundary):states.append('ENDED')
            else:states.append('PASS')
        except (ValueError,KeyError,TypeError,ZoneInfoNotFoundError):states.append('UNKNOWN')
    if 'ENDED' in states:return 'ENDED'
    if 'NOT_STARTED' in states:return 'NOT_STARTED'
    return 'UNKNOWN' if 'UNKNOWN' in states else 'PASS'
