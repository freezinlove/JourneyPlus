from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from journeyplus.config import Settings
from journeyplus.product.api import create_product_app
from journeyplus.product import startup


def _unavailable() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("database is down"))


def test_ready_product_database_is_migrated_without_starting_compose(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(startup, "_ping", lambda _engine: calls.append("ping"))
    monkeypatch.setattr(
        startup, "_upgrade_database", lambda: calls.append("upgrade")
    )
    monkeypatch.setattr(
        startup,
        "_start_compose_postgres",
        lambda: calls.append("compose"),
    )

    startup.prepare_product_database(Settings(database_url="sqlite://"), object())

    assert calls == ["ping", "upgrade"]


def test_local_product_database_is_started_then_migrated(monkeypatch) -> None:
    calls: list[str] = []
    attempts = iter([_unavailable(), None])

    def ping(_engine) -> None:
        calls.append("ping")
        failure = next(attempts)
        if failure is not None:
            raise failure

    monkeypatch.setattr(startup, "_ping", ping)
    monkeypatch.setattr(
        startup,
        "_start_compose_postgres",
        lambda: calls.append("compose"),
    )
    monkeypatch.setattr(
        startup, "_upgrade_database", lambda: calls.append("upgrade")
    )

    startup.prepare_product_database(
        Settings(
            database_url=(
                "postgresql+psycopg://journeyplus:secret@localhost:5433/journeyplus"
            )
        ),
        object(),
    )

    assert calls == ["ping", "compose", "ping", "upgrade"]


def test_remote_database_failure_does_not_attempt_local_compose(monkeypatch) -> None:
    calls: list[str] = []

    def fail_ping(_engine) -> None:
        raise _unavailable()

    monkeypatch.setattr(startup, "_ping", fail_ping)
    monkeypatch.setattr(
        startup,
        "_start_compose_postgres",
        lambda: calls.append("compose"),
    )

    with pytest.raises(startup.ProductDatabaseUnavailable, match="无法连接产品数据库"):
        startup.prepare_product_database(
            Settings(
                database_url=(
                    "postgresql+psycopg://journeyplus:secret@db.internal:5432/journeyplus"
                )
            ),
            object(),
        )

    assert calls == []


def test_product_api_returns_actionable_503_when_database_drops() -> None:
    class FailedContext:
        def __enter__(self):
            raise _unavailable()

        def __exit__(self, *_args):
            return False

    class FailedFactory:
        kw = {}

        def configure(self, **kwargs):
            self.kw.update(kwargs)

        def begin(self):
            return FailedContext()

    response = TestClient(create_product_app(FailedFactory())).get(
        "/v1/membership-catalog"
    )

    assert response.status_code == 503
    assert "product-api" in response.json()["detail"]
