from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from journeyplus.config import Settings


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ProductDatabaseUnavailable(RuntimeError):
    pass


def prepare_product_database(settings: Settings, engine: Engine) -> None:
    """Make the local product command fail early or prepare its Compose database."""

    try:
        _ping(engine)
    except SQLAlchemyError as initial_error:
        if not _uses_local_postgresql(settings.database_url):
            raise ProductDatabaseUnavailable(
                "无法连接产品数据库。请先启动配置的数据库，再重新运行 "
                "`uv run journeyplus product-api`。"
            ) from initial_error
        _start_compose_postgres()
        try:
            _ping(engine)
        except SQLAlchemyError as retry_error:
            raise ProductDatabaseUnavailable(
                "本地 PostgreSQL 已尝试启动，但仍无法连接。请运行 "
                "`docker compose ps` 检查 postgres 状态。"
            ) from retry_error

    try:
        _upgrade_database()
    except Exception as exc:
        raise ProductDatabaseUnavailable(
            "数据库已连接，但迁移升级失败。请运行 `uv run alembic upgrade head` "
            "查看具体错误。"
        ) from exc


def _ping(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _uses_local_postgresql(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return parsed.scheme.startswith("postgresql") and parsed.hostname in (
        _LOCAL_DATABASE_HOSTS
    )


def _start_compose_postgres() -> None:
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--wait", "postgres"],
            cwd=_PROJECT_ROOT,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ProductDatabaseUnavailable(
            "本地 PostgreSQL 未运行，且无法自动启动 Docker Compose。请先启动 "
            "Docker Desktop，再重新运行 `uv run journeyplus product-api`。"
        ) from exc


def _upgrade_database() -> None:
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
