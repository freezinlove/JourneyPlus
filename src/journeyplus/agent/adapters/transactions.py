"""Commit fence for tool effects: checkpoint, workspace, then business locks."""
from contextlib import contextmanager, nullcontext
from threading import RLock
from weakref import WeakKeyDictionary

_sqlite_locks=WeakKeyDictionary()
from time import monotonic
from datetime import timedelta
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from journeyplus.models import now_utc
from journeyplus.agent.harness.execution import active_call
from .models import RunCheckpoint


def check(context):
    if context and (context.cancel_token.is_set() or monotonic()>=context.deadline):
        raise TimeoutError('Tool execution canceled or deadline exceeded')


@contextmanager
def _transaction(factory):
    context=active_call.get()
    check(context)
    engine=factory.kw['bind']
    lock=_sqlite_locks.setdefault(engine,RLock()) if engine.dialect.name=='sqlite' else nullcontext()
    with lock, factory.begin() as session:
        if session.bind.dialect.name=='postgresql':
            remaining=max(1,min(10000,int((context.deadline-monotonic())*1000))) if context else 10000
            session.execute(text(f"SET LOCAL statement_timeout = {remaining}"))
            session.execute(text(f"SET LOCAL lock_timeout = {remaining}"))
        if context:
            from .artifacts import aware
            if context.run_id and context.lease_owner:
                checkpoint=session.get(RunCheckpoint,UUID(context.run_id),with_for_update=True)
                if (checkpoint is None or str(checkpoint.lease_owner)!=context.lease_owner
                    or checkpoint.cancel_requested or checkpoint.phase in {'COMPLETED','PARTIAL','CANCELED','FAILED'}
                    or checkpoint.heartbeat_at is None or aware(checkpoint.heartbeat_at)<now_utc()-timedelta(seconds=45)):
                    raise TimeoutError('Execution ownership no longer valid')
        if context:
            from journeyplus.models import AgentInteraction
            from .artifacts import aware
            workspace=session.get(AgentInteraction,UUID(context.workspace_id),with_for_update=True)
            if workspace is None or aware(workspace.expires_at)<=now_utc():
                raise TimeoutError('Workspace expired or replaced')
        check(context)
        yield session
        check(context)


@contextmanager
def transaction(factory):
    try:
        with _transaction(factory) as session:yield session
    except DBAPIError as error:
        if getattr(error.orig,'sqlstate',None) in {'57014','55P03'}:
            raise TimeoutError('Database execution or lock deadline exceeded') from error
        raise


@contextmanager
def read_session(factory):
    context=active_call.get()
    check(context)
    with factory() as session:
        try:
            if session.bind.dialect.name=='postgresql':
                remaining=max(1,min(10000,int((context.deadline-monotonic())*1000))) if context else 10000
                session.execute(text(f"SET LOCAL statement_timeout = {remaining}"))
                session.execute(text(f"SET LOCAL lock_timeout = {remaining}"))
            yield session
            check(context)
        except DBAPIError as error:
            if getattr(error.orig,'sqlstate',None) in {'57014','55P03'}:
                raise TimeoutError('Database read deadline exceeded') from error
            raise
        finally:session.rollback()
