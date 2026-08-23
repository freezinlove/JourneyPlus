from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.contracts import RunStatus
from journeyplus.models import JobRun

T = TypeVar("T")


class JobRunner:
    def __init__(self, session_factory: sessionmaker[Session], max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._session_factory = session_factory
        self._max_attempts = max_attempts

    def execute(
        self,
        *,
        idempotency_key: str,
        job_type: str,
        operation: Callable[[], T],
        serialize: Callable[[T], dict[str, Any]] | None = None,
    ) -> tuple[T | None, bool]:
        with self._session_factory() as session:
            existing = session.scalar(
                select(JobRun).where(JobRun.idempotency_key == idempotency_key)
            )
            if existing and existing.status == RunStatus.SUCCEEDED:
                return None, True
            if existing is None:
                existing = JobRun(
                    idempotency_key=idempotency_key,
                    job_type=job_type,
                    status=RunStatus.PENDING,
                )
                session.add(existing)
                session.commit()

        last_error: BaseException | None = None
        for attempt in range(1, self._max_attempts + 1):
            with self._session_factory() as session:
                run = session.scalar(
                    select(JobRun).where(JobRun.idempotency_key == idempotency_key)
                )
                assert run is not None
                run.status = RunStatus.RUNNING
                run.attempts = attempt
                run.started_at = run.started_at or datetime.now(UTC)
                session.commit()
            try:
                value = operation()
            except BaseException as exc:  # record operator interrupts before propagating
                last_error = exc
                with self._session_factory() as session:
                    run = session.scalar(
                        select(JobRun).where(JobRun.idempotency_key == idempotency_key)
                    )
                    assert run is not None
                    run.error = f"{type(exc).__name__}: {exc}"[:4000]
                    if attempt == self._max_attempts:
                        run.status = RunStatus.FAILED
                        run.finished_at = datetime.now(UTC)
                    session.commit()
                if not isinstance(exc, Exception):
                    raise
                continue

            with self._session_factory() as session:
                run = session.scalar(
                    select(JobRun).where(JobRun.idempotency_key == idempotency_key)
                )
                assert run is not None
                run.status = RunStatus.SUCCEEDED
                run.result = serialize(value) if serialize else None
                run.error = None
                run.finished_at = datetime.now(UTC)
                session.commit()
            return value, False

        assert last_error is not None
        raise last_error

    def run_isolated(
        self, operations: Mapping[str, Callable[[], T]]
    ) -> dict[str, T | Exception]:
        results: dict[str, T | Exception] = {}
        for source_id, operation in operations.items():
            try:
                results[source_id] = operation()
            except Exception as exc:
                results[source_id] = exc
        return results
