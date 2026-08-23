from __future__ import annotations

import base64
import zlib
from pathlib import Path
from urllib.parse import urlencode

import pytest

from journeyplus.sources.base import FetchResponse
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.gmail import (
    GMAIL_READONLY_SCOPE,
    QUERY,
    RECIPIENT_ALIAS,
    GmailStatusServicesAdapter,
)
from journeyplus.sources.registry import get_source_definition


FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, responses: dict[str, tuple[str, str] | str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        configured = self.responses[url]
        if isinstance(configured, tuple):
            body, final_url = configured
        else:
            body, final_url = configured, url
        content_type = "application/rss+xml" if body.startswith("<?xml") else "text/html"
        return FetchResponse(body=body, content_type=content_type, final_url=final_url)


@pytest.mark.parametrize(
    ("source_id", "fixture_name", "expects_article"),
    [
        ("ffb_elite_status_feed", "feed_summary.xml", True),
        ("awardwallet_elite_status_feed", "feed_summary.xml", True),
        ("loyaltylobby_feed", "feed_full.xml", False),
        ("frequentmiler_elite_status_feed", "feed_full.xml", False),
        ("verylvke_feed", "feed_full.xml", False),
    ],
)
def test_each_registered_feed_uses_its_fixed_body_strategy(
    source_id: str, fixture_name: str, expects_article: bool
) -> None:
    definition = get_source_definition(source_id)
    feed_url = str(definition.discovery_config["feed_url"])
    feed = (FIXTURES / fixture_name).read_text()
    article_url = "https://example.com/match"
    fetcher = FakeFetcher(
        {
            feed_url: feed,
            article_url: "<html><body><h1>Article body</h1></body></html>",
        }
    )
    adapter = build_adapter(source_id, fetcher=fetcher)
    item = adapter.discover()[0]
    raw = adapter.fetch(item)

    assert ("Article body" in raw.body) is expects_article
    assert (len(fetcher.calls) == 2) is expects_article
    assert raw.metadata["content_strategy"] == definition.content_strategy
    assert raw.metadata["title"] == item.title
    if source_id == "awardwallet_elite_status_feed":
        assert "pubDate" not in item.canonical_url
    if source_id == "loyaltylobby_feed":
        assert "omhide" not in item.canonical_url


class FakeGmailClient:
    def __init__(self) -> None:
        self.list_args: tuple[str, str] | None = None
        self.messages = {
            "allowed": _gmail_message(
                "allowed", "kirikoomiku+statusmatch@gmail.com", "Totally New Sender"
            ),
            "wrong-alias": _gmail_message(
                "wrong-alias", "kirikoomiku@gmail.com", "StatusMatch"
            ),
        }

    def list_labels(self):
        return [{"id": "Label_123", "name": "statusmatch"}]

    def list_messages(self, *, label_id: str, query: str):
        self.list_args = (label_id, query)
        return [{"id": key} for key in self.messages]

    def get_message(self, message_id: str):
        return self.messages[message_id]


def _gmail_message(
    message_id: str,
    recipient: str,
    sender: str,
    *,
    include_project_link: bool = True,
):
    final = (
        "https://www.statusmatch.com/email/click.php?"
        "uid=private-user&link=https%3A%2F%2Fclubavolta.statusmatch.com%2F"
    )
    token_payload = urlencode({"l": final}).encode()
    token = base64.urlsafe_b64encode(zlib.compress(token_payload)).decode().rstrip("=")
    tracking = f"https://email.mail.statusmatch.com/c/{token}"
    plain = base64.urlsafe_b64encode(b"A direct status match is open.").decode().rstrip("=")
    project_links = (
        f'<a href="{tracking}"><img alt="Get Started Button"></a>'
        '<a href="https://clubavolta.statusmatch.com/?private=drop">Club Avolta</a>'
        if include_project_link
        else ""
    )
    html = base64.urlsafe_b64encode(
        (
            "<html><body>"
            f"{project_links}"
            '<a href="https://example.com/unsubscribe">Unsubscribe</a>'
            "</body></html>"
        ).encode()
    ).decode().rstrip("=")
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["Label_123"],
        "snippet": "status match",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "To", "value": recipient},
                {"name": "From", "value": f"{sender} <news@example.net>"},
                {"name": "Subject", "value": "New match"},
                {"name": "Message-ID", "value": f"<{message_id}@example.net>"},
            ],
            "body": {},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": plain},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": html},
                },
            ],
        },
    }


def test_gmail_adapter_enforces_label_and_alias_but_no_sender_allowlist() -> None:
    client = FakeGmailClient()
    fetcher = FakeFetcher(
        {
            "https://clubavolta.statusmatch.com/": "<html><body>Activity overview</body></html>",
            "https://clubavolta.statusmatch.com/faq": "<html><body>Detailed eligibility</body></html>",
        }
    )
    adapter = GmailStatusServicesAdapter(client, project_fetcher=fetcher)
    items = adapter.discover()

    assert GMAIL_READONLY_SCOPE.endswith("gmail.readonly")
    assert client.list_args == ("Label_123", QUERY)
    assert [item.external_id for item in items] == [
        "allowed",
        "statusmatch-page:clubavolta.statusmatch.com:activity",
        "statusmatch-page:clubavolta.statusmatch.com:faq",
    ]
    assert items[0].raw_metadata["origin_provider"] == "STATUSMATCH"
    assert items[0].raw_metadata["document_role"] == "mail_discovery"
    assert "Get Started Button" in adapter.fetch(items[0]).body
    assert "Activity overview" in adapter.fetch(items[1]).body
    assert "Detailed eligibility" in adapter.fetch(items[2]).body
    assert fetcher.calls == [
        "https://clubavolta.statusmatch.com/",
        "https://clubavolta.statusmatch.com/faq",
    ]


def test_gmail_message_without_project_link_remains_discovery_only() -> None:
    client = FakeGmailClient()
    client.messages = {
        "allowed": _gmail_message(
            "allowed",
            "kirikoomiku+statusmatch@gmail.com",
            "StatusMatch",
            include_project_link=False,
        )
    }
    adapter = GmailStatusServicesAdapter(client, project_fetcher=FakeFetcher({}))

    items = adapter.discover()

    assert len(items) == 1
    assert items[0].raw_metadata["document_role"] == "mail_discovery"
    assert items[0].raw_metadata["project_statusmatch_hosts"] == []


def test_gmail_two_messages_deduplicate_project_pages_by_subdomain() -> None:
    client = FakeGmailClient()
    client.messages = {
        "first": _gmail_message(
            "first", RECIPIENT_ALIAS, "StatusMatch"
        ),
        "second": _gmail_message(
            "second", RECIPIENT_ALIAS, "StatusMatch"
        ),
    }
    adapter = GmailStatusServicesAdapter(
        client,
        project_fetcher=FakeFetcher(
            {
                "https://clubavolta.statusmatch.com/": "<html>Activity</html>",
                "https://clubavolta.statusmatch.com/faq": "<html>FAQ</html>",
            }
        ),
    )

    items = adapter.discover()

    assert [item.external_id for item in items] == [
        "first",
        "second",
        "statusmatch-page:clubavolta.statusmatch.com:activity",
        "statusmatch-page:clubavolta.statusmatch.com:faq",
    ]
