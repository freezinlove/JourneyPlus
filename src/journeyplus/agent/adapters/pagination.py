"""Bind continuations to their workspace, input and immutable result prefix."""
import base64
import json
from .artifacts import digest


def page(rows, *, binding, identity, cursor=None, limit=10):
    key = digest(binding)
    offset = 0
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if token['key'] != key or type(token['offset']) is not int or token['offset'] < 0:
                raise ValueError()
            end = next(i for i, row in enumerate(rows) if identity(row) == token['last'])
            rows = rows[:end + 1]
            if digest([identity(row) for row in rows]) != token['snapshot']:
                raise ValueError()
            offset = token['offset']
            if offset > len(rows):
                raise ValueError()
        except (ValueError, KeyError, TypeError, StopIteration, UnicodeError):
            raise ValueError('STALE_REFERENCE: cursor input or snapshot changed') from None
    selected = rows[offset:offset + limit]
    next_cursor = None
    if offset + limit < len(rows):
        token = {'key': key, 'snapshot': digest([identity(row) for row in rows]),
                 'last': identity(rows[-1]), 'offset': offset + limit}
        next_cursor = base64.urlsafe_b64encode(json.dumps(token).encode()).decode()
    return selected, next_cursor, len(rows)
