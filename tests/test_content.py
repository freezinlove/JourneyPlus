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


def test_mail_cleaning_preserves_image_project_link_and_strips_unrelated_link() -> None:
    cleaned = lightly_clean(
        RawDocument(
            source_id="status_services_mail",
            external_id="mail-one",
            canonical_url="https://mail.google.com/mail/u/0/?message_id=mail-one",
            body=(
                '<html><body><a href="https://clubavolta.statusmatch.com/?uid=x">'
                '<img alt="Get Started Button"></a>'
                '<a href="https://example.com/unsubscribe">Unsubscribe</a>'
                "</body></html>"
            ),
            content_type="text/html",
            metadata={"document_role": "mail_discovery"},
        )
    )

    assert "clubavolta.statusmatch.com" in cleaned.normalized_body
    assert "Get Started Button" in cleaned.normalized_body
    assert "example.com/unsubscribe" not in cleaned.normalized_body
    assert "Unsubscribe" in cleaned.normalized_body


def test_linked_statusmatch_page_keeps_public_links_and_tables() -> None:
    cleaned = lightly_clean(
        RawDocument(
            source_id="status_services_mail",
            external_id="statusmatch-page:example.statusmatch.com:faq",
            canonical_url="https://example.statusmatch.com/faq",
            body=(
                "<html><body><table><tr><th>Source</th><th>Gold</th></tr>"
                "<tr><td>Example Air</td><td>Platinum</td></tr></table>"
                '<a href="https://example-air.com/apply">Apply now</a>'
                '<a href="https://example.com/terms">Terms</a>'
                "</body></html>"
            ),
            content_type="text/html",
            metadata={"document_role": "linked_statusmatch_page"},
        )
    )

    assert "Example Air" in cleaned.normalized_body
    assert "Platinum" in cleaned.normalized_body
    assert "https://example-air.com/apply" in cleaned.normalized_body
    assert "https://example.com/terms" in cleaned.normalized_body


def test_linked_statusmatch_page_ignores_cloudflare_email_token_churn() -> None:
    def clean(token: str):
        return lightly_clean(
            RawDocument(
                source_id="status_services_mail",
                external_id="statusmatch-page:example.statusmatch.com:faq",
                canonical_url="https://example.statusmatch.com/faq",
                body=(
                    '<html><body><p>Stable offer</p><a href="/cdn-cgi/l/'
                    f'email-protection#{token}">[email protected]</a></body></html>'
                ),
                content_type="text/html",
                metadata={"document_role": "linked_statusmatch_page"},
            )
        )

    first = clean("012345")
    second = clean("abcdef")

    assert first.raw_hash != second.raw_hash
    assert first.normalized_body == second.normalized_body
    assert first.normalized_hash == second.normalized_hash
    assert "012345" not in first.normalized_body
    assert "abcdef" not in second.normalized_body


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


def test_same_item_dynamic_html_does_not_version_unchanged_normalized_content(
    db_session,
) -> None:
    seed_sources(db_session)
    service = IngestionService(db_session)
    item = _item("dynamic", "https://example.com/dynamic")
    first = service.ingest(
        item,
        _raw(
            "dynamic",
            "https://example.com/dynamic",
            "<html><body><p>Stable offer</p><form>token-one</form></body></html>",
        ),
    )
    second = service.ingest(
        item,
        _raw(
            "dynamic",
            "https://example.com/dynamic",
            "<html><body><p>Stable offer</p><form>token-two</form></body></html>",
        ),
    )

    assert first.new_version is True
    assert second.new_version is False
    assert second.document_version.id == first.document_version.id


def test_parser_version_change_creates_a_new_normalized_document(
    db_session, monkeypatch
) -> None:
    seed_sources(db_session)
    service = IngestionService(db_session)
    item = _item("parser", "https://example.com/parser")
    raw = _raw("parser", "https://example.com/parser", "<p>Stable body</p>")

    monkeypatch.setattr("journeyplus.content.cleaner.PARSER_VERSION", "parser-one")
    first = service.ingest(item, raw)
    monkeypatch.setattr("journeyplus.content.cleaner.PARSER_VERSION", "parser-two")
    second = service.ingest(item, raw)

    assert first.new_version is True
    assert second.new_version is True
    assert second.document_version.id != first.document_version.id
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 2
