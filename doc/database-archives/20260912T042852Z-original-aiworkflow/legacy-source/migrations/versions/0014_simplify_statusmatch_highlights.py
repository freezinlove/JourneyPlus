"""remove stored excerpts from StatusMatch article highlights

Revision ID: 0014_simple_highlights
Revises: 0013_buy_points
Create Date: 2026-08-28
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "0014_simple_highlights"
down_revision = "0013_buy_points"
branch_labels = None
depends_on = None


def _highlight_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    highlights: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("text")
        else:
            text = None
        if isinstance(text, str) and (normalized := " ".join(text.split())):
            highlights.append(normalized)
    return highlights


def upgrade() -> None:
    connection = op.get_bind()
    supplements = sa.table(
        "statusmatch_article_supplements",
        sa.column("id", sa.Uuid()),
        sa.column("highlights", sa.JSON()),
        sa.column("mapping_claims", sa.JSON()),
    )
    for row in connection.execute(
        sa.select(
            supplements.c.id,
            supplements.c.highlights,
            supplements.c.mapping_claims,
        )
    ):
        highlights = _highlight_texts(row.highlights)
        if highlights != row.highlights or row.mapping_claims:
            connection.execute(
                supplements.update()
                .where(supplements.c.id == row.id)
                .values(highlights=highlights, mapping_claims=[])
            )

    analyses = sa.table(
        "analysis_runs",
        sa.column("id", sa.Uuid()),
        sa.column("stage", sa.String(length=100)),
        sa.column("schema_version", sa.String(length=100)),
        sa.column("result", sa.JSON()),
    )
    for row in connection.execute(
        sa.select(analyses.c.id, analyses.c.result).where(
            analyses.c.stage == "STATUSMATCH_ARTICLE_HIGHLIGHTS",
            analyses.c.result.is_not(None),
        )
    ):
        result = row.result if isinstance(row.result, dict) else {}
        connection.execute(
            analyses.update()
            .where(analyses.c.id == row.id)
            .values(
                schema_version="3",
                result={
                    "schema_version": "3",
                    "highlights": _highlight_texts(result.get("highlights")),
                },
            )
        )


def downgrade() -> None:
    # Removed excerpts and reasoning cannot be reconstructed without inventing data.
    pass
