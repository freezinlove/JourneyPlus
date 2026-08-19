from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.content.cleaner import lightly_clean
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import DocumentVersion, SourceItem


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_item: SourceItem
    document_version: DocumentVersion
    new_item: bool
    new_version: bool


class IngestionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def should_fetch(self, item: DiscoveredItem) -> bool:
        source_item = self._find_item(item)
        if source_item is None:
            return True
        source_item.observed_at = item.observed_at
        source_item.raw_metadata = item.raw_metadata
        source_item.title = item.title or source_item.title
        if item.discovery_fingerprint is None:
            return False
        return source_item.discovery_fingerprint != item.discovery_fingerprint

    def ingest(self, item: DiscoveredItem, raw: RawDocument) -> IngestionResult:
        source_item = self._find_item(item)
        new_item = source_item is None
        if source_item is None:
            source_item = SourceItem(
                source_id=item.source_id,
                external_id=item.external_id,
                discovered_url=item.discovered_url,
                canonical_url=item.canonical_url,
                title=item.title,
                published_at=item.published_at,
                observed_at=item.observed_at,
                discovery_fingerprint=item.discovery_fingerprint,
                raw_metadata=item.raw_metadata,
            )
            self._session.add(source_item)
            self._session.flush()
        else:
            source_item.title = item.title or source_item.title
            source_item.observed_at = item.observed_at
            source_item.raw_metadata = item.raw_metadata
            source_item.discovery_fingerprint = item.discovery_fingerprint

        cleaned = lightly_clean(raw)
        existing = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.source_item_id == source_item.id,
                DocumentVersion.raw_hash == cleaned.raw_hash,
            )
        )
        if existing is not None:
            return IngestionResult(source_item, existing, new_item, False)

        duplicate = self._session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.normalized_hash == cleaned.normalized_hash)
            .order_by(DocumentVersion.created_at.asc())
            .limit(1)
        )
        version = DocumentVersion(
            source_item_id=source_item.id,
            canonical_url=raw.canonical_url,
            raw_body=None if raw.storage_mode == "hash_only" else cleaned.raw_body,
            normalized_body=cleaned.normalized_body,
            content_type=raw.content_type,
            storage_mode=raw.storage_mode,
            raw_hash=cleaned.raw_hash,
            normalized_hash=cleaned.normalized_hash,
            parser_version=cleaned.parser_version,
            fetched_at=raw.fetched_at,
            duplicate_of_id=duplicate.id if duplicate is not None else None,
        )
        self._session.add(version)
        self._session.flush()
        return IngestionResult(source_item, version, new_item, True)

    def _find_item(self, item: DiscoveredItem) -> SourceItem | None:
        by_id = self._session.scalar(
            select(SourceItem).where(
                SourceItem.source_id == item.source_id,
                SourceItem.external_id == item.external_id,
            )
        )
        if by_id is not None:
            return by_id
        return self._session.scalar(
            select(SourceItem).where(
                SourceItem.source_id == item.source_id,
                SourceItem.canonical_url == item.canonical_url,
            )
        )
