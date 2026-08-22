from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_all_v1_tables(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migration.sqlite"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "sources",
        "collection_runs",
        "source_items",
        "document_versions",
        "analysis_runs",
        "status_events",
        "event_revisions",
        "event_evidence",
        "fact_sets",
        "briefs",
        "review_decisions",
        "gold_cases",
        "job_runs",
    } <= tables


def test_opportunity_type_migration_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "opportunity_type" not in {
        column["name"] for column in inspect(engine).get_columns("status_events")
    }
    engine.dispose()

    command.downgrade(config, "0001_status_opportunity_v1")
    engine = create_engine(database_url)
    opportunity_type = next(
        column
        for column in inspect(engine).get_columns("status_events")
        if column["name"] == "opportunity_type"
    )
    assert opportunity_type["nullable"] is False
    assert opportunity_type["default"] is None
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert "opportunity_type" not in {
        column["name"] for column in inspect(engine).get_columns("status_events")
    }
    engine.dispose()
