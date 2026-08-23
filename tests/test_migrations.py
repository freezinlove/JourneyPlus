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
        "automation_leases",
        "automation_runs",
        "source_automation_states",
        "initialization_runs",
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


def test_status_event_lifecycle_migration_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'lifecycle.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0002_remove_opportunity_type")
    engine = create_engine(database_url)
    before = {
        column["name"] for column in inspect(engine).get_columns("status_events")
    }
    assert "lifecycle_status" not in before
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("status_events")
    }
    assert {
        "application_start_at",
        "application_deadline_at",
        "lifecycle_status",
        "archived_at",
    } <= columns.keys()
    assert columns["lifecycle_status"]["nullable"] is False
    assert "UNKNOWN" in str(columns["lifecycle_status"]["default"])
    assert "ix_status_events_lifecycle_archived" in {
        index["name"] for index in inspect(engine).get_indexes("status_events")
    }
    engine.dispose()

    command.downgrade(config, "0002_remove_opportunity_type")
    engine = create_engine(database_url)
    after = {
        column["name"] for column in inspect(engine).get_columns("status_events")
    }
    assert "application_start_at" not in after
    assert "application_deadline_at" not in after
    assert "lifecycle_status" not in after
    assert "archived_at" not in after
    engine.dispose()


def test_daily_automation_migration_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'automation.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0003_status_event_lifecycle")
    engine = create_engine(database_url)
    assert "automation_runs" not in set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "automation_leases",
        "automation_runs",
        "source_automation_states",
        "initialization_runs",
    } <= tables
    run_columns = {
        column["name"] for column in inspect(engine).get_columns("automation_runs")
    }
    assert {"day_bucket", "model_calls", "backlog_count"} <= run_columns
    engine.dispose()

    command.downgrade(config, "0003_status_event_lifecycle")
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert "automation_leases" not in tables
    assert "automation_runs" not in tables
    assert "source_automation_states" not in tables
    assert "initialization_runs" not in tables
    engine.dispose()
