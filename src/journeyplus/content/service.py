from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from journeyplus.content.cleaner import PARSER_VERSION, lightly_clean
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
        if item.raw_metadata.get("refresh_on_discovery") is True:
            return True
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
                raw_metadata={**item.raw_metadata, **raw.metadata},
            )
            self._session.add(source_item)
            self._session.flush()
        else:
            source_item.title = item.title or source_item.title
            source_item.observed_at = item.observed_at
            source_item.raw_metadata = {**item.raw_metadata, **raw.metadata}
            source_item.discovery_fingerprint = item.discovery_fingerprint

        cleaned = lightly_clean(raw)
        existing = self._session.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.source_item_id == source_item.id,
                DocumentVersion.parser_version == cleaned.parser_version,
                or_(
                    DocumentVersion.raw_hash == cleaned.raw_hash,
                    DocumentVersion.normalized_hash == cleaned.normalized_hash,
                ),
            )
            .order_by(DocumentVersion.created_at.asc())
            .limit(1)
        )
        if existing is not None:
            return IngestionResult(source_item, existing, new_item, False)

        duplicate = self._session.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.normalized_hash == cleaned.normalized_hash,
                DocumentVersion.parser_version == cleaned.parser_version,
            )
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

    def current_document(self, item: DiscoveredItem) -> DocumentVersion | None:
        source_item = self._find_item(item)
        if source_item is None:
            return None
        return self._session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.source_item_id == source_item.id)
            .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
            .limit(1)
        )

    def reparse_outdated_snapshots(
        self,
        *,
        source_id: str,
    ) -> list[IngestionResult]:
        latest = aliased(DocumentVersion)
        latest_document_id = (
            select(latest.id)
            .where(latest.source_item_id == SourceItem.id)
            .order_by(latest.created_at.desc(), latest.id.desc())
            .limit(1)
            .correlate(SourceItem)
            .scalar_subquery()
        )
        rows = list(
            self._session.execute(
                select(SourceItem, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.id == latest_document_id)
                .where(
                    SourceItem.source_id == source_id,
                    DocumentVersion.parser_version != PARSER_VERSION,
                    DocumentVersion.raw_body.is_not(None),
                )
            )
        )
        results: list[IngestionResult] = []
        for source_item, document in rows:
            item = DiscoveredItem(
                source_id=source_item.source_id,
                external_id=source_item.external_id,
                discovered_url=source_item.discovered_url,
                canonical_url=source_item.canonical_url,
                title=source_item.title,
                published_at=source_item.published_at,
                observed_at=datetime.now(UTC),
                discovery_fingerprint=source_item.discovery_fingerprint,
                raw_metadata=source_item.raw_metadata or {},
            )
            raw = RawDocument(
                source_id=source_item.source_id,
                external_id=source_item.external_id,
                canonical_url=document.canonical_url,
                body=document.raw_body or "",
                content_type=document.content_type,
                storage_mode=document.storage_mode,
                metadata=source_item.raw_metadata or {},
            )
            result = self.ingest(item, raw)
            if result.new_version:
                results.append(result)
        return results

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
