from __future__ import annotations

from sqlalchemy import select

from journeyplus.contracts import RunStatus
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import JobRun


def test_job_runner_retries_and_is_idempotent(session_factory) -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "ok"

    runner = JobRunner(session_factory, max_attempts=2)
    value, skipped = runner.execute(
        idempotency_key="job-1", job_type="test", operation=operation
    )
    assert value == "ok"
    assert skipped is False
    assert attempts == 2

    value, skipped = runner.execute(
        idempotency_key="job-1", job_type="test", operation=operation
    )
    assert value is None
    assert skipped is True
    assert attempts == 2

    with session_factory() as session:
        run = session.scalar(select(JobRun).where(JobRun.idempotency_key == "job-1"))
        assert run is not None
        assert run.status == RunStatus.SUCCEEDED
        assert run.attempts == 2


def test_source_operations_are_isolated(session_factory) -> None:
    runner = JobRunner(session_factory)
    results = runner.run_isolated(
        {
            "good": lambda: "done",
            "bad": lambda: (_ for _ in ()).throw(RuntimeError("broken")),
        }
    )
    assert results["good"] == "done"
    assert isinstance(results["bad"], RuntimeError)

