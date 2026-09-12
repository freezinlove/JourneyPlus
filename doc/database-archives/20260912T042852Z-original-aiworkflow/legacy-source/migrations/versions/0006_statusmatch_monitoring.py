"""add persistent StatusMatch monitoring

Revision ID: 0006_statusmatch_monitoring
Revises: 0005_document_parser_versions
Create Date: 2026-08-24
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0006_statusmatch_monitoring"
down_revision = "0005_document_parser_versions"
branch_labels = None
depends_on = None


_EXTERNAL_ID_RE = re.compile(
    r"^statusmatch-page:(?P<host>[a-z0-9][a-z0-9-]{0,62}\.statusmatch\.com):"
    r"(?P<kind>activity|faq)$"
)


def upgrade() -> None:
    with op.batch_alter_table("status_events") as batch_op:
        batch_op.add_column(
            sa.Column("archive_reason", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("closure_document_version_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_status_events_closure_document_version_id",
            "document_versions",
            ["closure_document_version_id"],
            ["id"],
        )
    op.create_table(
        "statusmatch_watches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_event_id", sa.Uuid(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["current_event_id"], ["status_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host"),
    )
    op.create_table(
        "statusmatch_watch_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("watch_id", sa.Uuid(), nullable=False),
        sa.Column("page_kind", sa.String(length=20), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("current_document_version_id", sa.Uuid(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_document_version_id"], ["document_versions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["watch_id"], ["statusmatch_watches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
        sa.UniqueConstraint("watch_id", "page_kind"),
    )
    _backfill_existing_statusmatch_pages()


def downgrade() -> None:
    op.drop_table("statusmatch_watch_pages")
    op.drop_table("statusmatch_watches")
    with op.batch_alter_table("status_events") as batch_op:
        batch_op.drop_constraint(
            "fk_status_events_closure_document_version_id", type_="foreignkey"
        )
        batch_op.drop_column("closure_document_version_id")
        batch_op.drop_column("archive_reason")


def _backfill_existing_statusmatch_pages() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, external_id, canonical_url
            FROM source_items
            WHERE source_id = 'status_services_mail'
              AND external_id LIKE 'statusmatch-page:%'
            """
        )
    ).mappings()
    projects: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        match = _EXTERNAL_ID_RE.fullmatch(str(row["external_id"]))
        if match is None:
            continue
        host = match.group("host")
        kind = match.group("kind")
        expected_url = (
            f"https://{host}/" if kind == "activity" else f"https://{host}/faq"
        )
        if _normalized_url(str(row["canonical_url"])) != expected_url:
            continue
        projects.setdefault(host, {})[kind] = dict(row)

    now = datetime.now(UTC)
    for host, pages in sorted(projects.items()):
        if set(pages) != {"activity", "faq"}:
            continue
        watch_id = uuid4().hex
        current_documents = {
            kind: _latest_document_id(bind, page["id"])
            for kind, page in pages.items()
        }
        current_event_id = _unambiguous_event_id(
            bind, [page["id"] for page in pages.values()]
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO statusmatch_watches
                    (id, host, status, current_event_id, last_checked_at,
                     last_changed_at, last_error, created_at, updated_at)
                VALUES
                    (:id, :host, :status, :current_event_id, NULL,
                     NULL, NULL, :created_at, :updated_at)
                """
            ),
            {
                "id": watch_id,
                "host": host,
                "status": (
                    "ACTIVE"
                    if all(current_documents.values())
                    else "PENDING"
                ),
                "current_event_id": current_event_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        for kind in ("activity", "faq"):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO statusmatch_watch_pages
                        (id, watch_id, page_kind, canonical_url,
                         current_document_version_id, last_checked_at,
                         last_changed_at, last_error, created_at, updated_at)
                    VALUES
                        (:id, :watch_id, :page_kind, :canonical_url,
                         :current_document_version_id, NULL,
                         NULL, NULL, :created_at, :updated_at)
                    """
                ),
                {
                    "id": uuid4().hex,
                    "watch_id": watch_id,
                    "page_kind": kind,
                    "canonical_url": (
                        f"https://{host}/"
                        if kind == "activity"
                        else f"https://{host}/faq"
                    ),
                    "current_document_version_id": current_documents[kind],
                    "created_at": now,
                    "updated_at": now,
                },
            )


def _latest_document_id(bind, source_item_id):
    return bind.execute(
        sa.text(
            """
            SELECT id
            FROM document_versions
            WHERE source_item_id = :source_item_id
            ORDER BY fetched_at DESC, created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"source_item_id": source_item_id},
    ).scalar_one_or_none()


def _unambiguous_event_id(bind, source_item_ids: list[object]):
    placeholders = ", ".join(
        f":source_item_id_{index}" for index in range(len(source_item_ids))
    )
    params = {
        f"source_item_id_{index}": value
        for index, value in enumerate(source_item_ids)
    }
    event_ids = list(
        bind.execute(
            sa.text(
                f"""
                SELECT DISTINCT ee.event_id
                FROM event_evidence AS ee
                JOIN document_versions AS dv
                  ON dv.id = ee.document_version_id
                JOIN status_events AS se
                  ON se.id = ee.event_id
                WHERE dv.source_item_id IN ({placeholders})
                  AND se.archived_at IS NULL
                  AND se.merged_into_id IS NULL
                """
            ),
            params,
        ).scalars()
    )
    return event_ids[0] if len(event_ids) == 1 else None


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold().rstrip(".")
    path = parsed.path.rstrip("/")
    return f"https://{host}{path or '/'}"
