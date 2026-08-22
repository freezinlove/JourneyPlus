from __future__ import annotations

from sqlalchemy.orm import Session

from journeyplus.models import DocumentVersion, SourceItem


def catalog_authoritative_program(
    session: Session, document: DocumentVersion
) -> str | None:
    """Return the FFB catalog's left-column program when the source supplies one."""

    item = session.get(SourceItem, document.source_item_id)
    if item is None:
        return None
    metadata = item.raw_metadata or {}
    reported_source_id = metadata.get("source_id", item.source_id)
    program = metadata.get("program")
    if reported_source_id != "ffb_status_match_catalog" or not isinstance(
        program, str
    ):
        return None
    normalized = program.strip()
    return normalized if 0 < len(normalized) <= 200 else None
