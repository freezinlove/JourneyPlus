from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def test_migration_revision_ids_fit_postgresql_alembic_version_column() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert all(len(revision.revision) <= 32 for revision in scripts.walk_revisions())


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
        "statusmatch_watches",
        "statusmatch_watch_pages",
        "statusmatch_change_sets",
        "statusmatch_article_routes",
        "statusmatch_article_supplements",
        "article_analyses",
        "article_opportunities",
        "article_briefs",
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


def test_generic_article_v2_migration_round_trips_without_removing_v1_tables(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'article-v2.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0009_statusmatch_articles")
    engine = create_engine(database_url)
    before = set(inspect(engine).get_table_names())
    assert "status_events" in before
    assert "article_analyses" not in before
    assert "mapping_claims" not in {
        column["name"]
        for column in inspect(engine).get_columns("statusmatch_article_supplements")
    }
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    at_head = set(inspect(engine).get_table_names())
    assert {"article_analyses", "article_opportunities", "article_briefs"} <= at_head
    assert before <= at_head
    assert "mapping_claims" in {
        column["name"]
        for column in inspect(engine).get_columns("statusmatch_article_supplements")
    }
    engine.dispose()

    command.downgrade(config, "0009_statusmatch_articles")
    engine = create_engine(database_url)
    after = set(inspect(engine).get_table_names())
    assert before == after
    assert "mapping_claims" not in {
        column["name"]
        for column in inspect(engine).get_columns("statusmatch_article_supplements")
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


def test_document_parser_version_constraint_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'parser-version.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0004_daily_automation")
    engine = create_engine(database_url)
    before = {
        tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("document_versions")
    }
    assert ("source_item_id", "raw_hash") in before
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    upgraded = {
        tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("document_versions")
    }
    assert ("source_item_id", "raw_hash", "parser_version") in upgraded
    assert ("source_item_id", "raw_hash") not in upgraded
    engine.dispose()

    command.downgrade(config, "0004_daily_automation")
    engine = create_engine(database_url)
    downgraded = {
        tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("document_versions")
    }
    assert ("source_item_id", "raw_hash") in downgraded
    engine.dispose()


def test_statusmatch_monitoring_migration_backfills_complete_page_pairs(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'statusmatch-watch.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "0005_document_parser_versions")
    engine = create_engine(database_url)
    now = "2026-08-24 00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO sources
                    (id, name, adapter_type, discovery_config, access_policy,
                     collection_cadence, automatic_scheduling, enabled,
                     created_at, updated_at)
                VALUES
                    ('status_services_mail', 'StatusMatch Mail', 'gmail', '{}', '{}',
                     'P1D', 0, 1, :now, :now)
                """
            ),
            {"now": now},
        )
        for index, kind in enumerate(("activity", "faq"), start=1):
            item_id = f"{index:032x}"
            document_id = f"{index + 10:032x}"
            url = (
                "https://example.statusmatch.com/"
                if kind == "activity"
                else "https://example.statusmatch.com/faq"
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source_items
                        (id, source_id, external_id, discovered_url, canonical_url,
                         title, published_at, observed_at, discovery_fingerprint,
                         raw_metadata, created_at, updated_at)
                    VALUES
                        (:id, 'status_services_mail', :external_id, :url, :url,
                         '', NULL, :now, NULL, '{}', :now, :now)
                    """
                ),
                {
                    "id": item_id,
                    "external_id": (
                        f"statusmatch-page:example.statusmatch.com:{kind}"
                    ),
                    "url": url,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO document_versions
                        (id, source_item_id, canonical_url, raw_body, normalized_body,
                         content_type, storage_mode, raw_hash, normalized_hash,
                         parser_version, fetched_at, duplicate_of_id,
                         created_at, updated_at)
                    VALUES
                        (:id, :source_item_id, :url, '<html></html>', 'body',
                         'text/html', 'test', :raw_hash, :normalized_hash,
                         'test', :now, NULL, :now, :now)
                    """
                ),
                {
                    "id": document_id,
                    "source_item_id": item_id,
                    "url": url,
                    "raw_hash": f"{index:064x}",
                    "normalized_hash": f"{index + 10:064x}",
                    "now": now,
                },
            )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM statusmatch_watches")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM statusmatch_watch_pages")
        ) == 2
        assert connection.scalar(
            text(
                "SELECT count(*) FROM statusmatch_watch_pages "
                "WHERE current_document_version_id IS NOT NULL"
            )
        ) == 2
    engine.dispose()


def test_statusmatch_project_changeset_migration_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'statusmatch-project.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0006_statusmatch_monitoring")
    engine = create_engine(database_url)
    assert "statusmatch_change_sets" not in set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "statusmatch_change_sets" in set(inspector.get_table_names())
    assert {
        "event_id",
        "from_fact_set_id",
        "to_fact_set_id",
        "activity_document_version_id",
        "faq_document_version_id",
        "kind",
        "changes",
    } <= {
        column["name"]
        for column in inspector.get_columns("statusmatch_change_sets")
    }
    assert "ix_statusmatch_change_sets_event_created" in {
        index["name"]
        for index in inspector.get_indexes("statusmatch_change_sets")
    }
    assert (
        "event_id",
        "activity_document_version_id",
        "faq_document_version_id",
        "to_fact_set_id",
    ) in {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(
            "statusmatch_change_sets"
        )
    }
    engine.dispose()

    command.downgrade(config, "0006_statusmatch_monitoring")
    engine = create_engine(database_url)
    assert "statusmatch_change_sets" not in set(inspect(engine).get_table_names())
    engine.dispose()


def test_statusmatch_article_migration_round_trips_on_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'statusmatch-articles.sqlite'}"
    monkeypatch.setenv("JOURNEYPLUS_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "0008_statusmatch_changeset")
    engine = create_engine(database_url)
    assert "statusmatch_article_routes" not in set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "statusmatch_article_routes",
        "statusmatch_article_supplements",
    } <= set(inspector.get_table_names())
    assert (
        "document_version_id",
        "project_host",
    ) in {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("statusmatch_article_routes")
    }
    assert (
        "route_id",
        "fact_set_id",
        "brief_id",
        "input_version",
    ) in {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints(
            "statusmatch_article_supplements"
        )
    }
    engine.dispose()

    command.downgrade(config, "0008_statusmatch_changeset")
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert "statusmatch_article_routes" not in tables
    assert "statusmatch_article_supplements" not in tables
    engine.dispose()
