from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from journeyplus.content.cleaner import lightly_clean
from journeyplus.content.service import IngestionService
from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import DocumentVersion, SourceItem
from journeyplus.sources.registry import seed_sources


def _item(external_id: str, url: str) -> DiscoveredItem:
    return DiscoveredItem(
        source_id="ffb_elite_status_feed",
        external_id=external_id,
        discovered_url=url,
        canonical_url=canonicalize_url(url),
        title="A title",
        observed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _raw(external_id: str, url: str, body: str) -> RawDocument:
    return RawDocument(
        source_id="ffb_elite_status_feed",
        external_id=external_id,
        canonical_url=canonicalize_url(url),
        body=body,
    )


def test_url_canonicalization_removes_tracking_and_normalizes() -> None:
    assert canonicalize_url(
        "HTTPS://Example.COM:443/a?b=2&utm_source=x&pubDate=3&a=1#top"
    ) == "https://example.com/a?a=1&b=2"


def test_light_cleaning_keeps_structure_and_removes_page_chrome() -> None:
    cleaned = lightly_clean(
        _raw(
            "1",
            "https://example.com/1",
            "<html><body><nav>Menu</nav><h1>Offer</h1><p>Keep <b>this</b>.</p>"
            "<script>secret()</script></body></html>",
        )
    )
    assert "# Offer" in cleaned.normalized_body
    assert "Keep **this**" in cleaned.normalized_body
    assert "Menu" not in cleaned.normalized_body
    assert "secret" not in cleaned.normalized_body


def test_discovery_and_content_deduplication_and_versioning(db_session) -> None:
    seed_sources(db_session)
    service = IngestionService(db_session)
    first = service.ingest(
        _item("guid-1", "https://example.com/a?utm_source=x"),
        _raw("guid-1", "https://example.com/a", "<p>Version one</p>"),
    )
    exact_repeat = service.ingest(
        _item("guid-1", "https://example.com/a"),
        _raw("guid-1", "https://example.com/a", "<p>Version one</p>"),
    )
    same_url_other_id = service.ingest(
        _item("changed-guid", "https://example.com/a"),
        _raw("changed-guid", "https://example.com/a", "<p>Version one</p>"),
    )
    changed = service.ingest(
        _item("guid-1", "https://example.com/a"),
        _raw("guid-1", "https://example.com/a", "<p>Version two</p>"),
    )
    duplicate_content = service.ingest(
        _item("guid-2", "https://example.com/b"),
        _raw("guid-2", "https://example.com/b", "<p>Version two</p>"),
    )

    assert first.new_item and first.new_version
    assert not exact_repeat.new_version
    assert same_url_other_id.source_item.id == first.source_item.id
    assert changed.new_version
    assert duplicate_content.document_version.duplicate_of_id == changed.document_version.id
    assert db_session.scalar(select(func.count()).select_from(SourceItem)) == 2
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 3

