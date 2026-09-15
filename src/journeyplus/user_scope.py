"""Request/task-local identity. Never supplied by model tool arguments."""
from contextvars import ContextVar
from contextlib import contextmanager
from uuid import UUID

OWNER_ID = UUID('00000000-0000-0000-0000-000000000001')
# Local maintenance/legacy data belongs to the original owner unless explicitly scoped.
_current = ContextVar('journeyplus_user', default=OWNER_ID)

def user_id():
    value=_current.get()
    if value is None:raise PermissionError('A user scope is required')
    return value

@contextmanager
def acting_as(identity):
    token=_current.set(UUID(str(identity)) if identity is not None else None)
    try:yield
    finally:_current.reset(token)
