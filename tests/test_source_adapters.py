from __future__ import annotations

import base64
from pathlib import Path

import pytest

from journeyplus.sources.base import FetchResponse
from journeyplus.sources.catalog import StaticCatalogAdapter, parse_catalog_records
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.gmail import (
    GMAIL_READONLY_SCOPE,
    QUERY,
    GmailStatusServicesAdapter,
)
from journeyplus.sources.registry import get_source_definition
from journeyplus.sources.statusmatcher import StatusMatcherAdapter


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


def test_catalog_top_level_fingerprint_is_stable_but_content_change_is_visible() -> None:
    url = "https://www.frequentflyerbonuses.com/statusmatchoffers.html"
    html = (FIXTURES / "ffb_catalog.html").read_text()
    adapter = StaticCatalogAdapter(catalog_url=url, fetcher=FakeFetcher({url: html}))
    first = adapter.discover()
    changed_html = html.replace("through December", "through January")
    changed_adapter = StaticCatalogAdapter(
        catalog_url=url, fetcher=FakeFetcher({url: changed_html})
    )
    second = changed_adapter.discover()

    assert len(first) == 2
    assert first[0].title == "Example Air"
    assert first[0].raw_metadata["section"] == "airline"
    assert first[1].raw_metadata["section"] == "hotel"
    assert first[0].external_id == second[0].external_id
    assert first[0].discovery_fingerprint != second[0].discovery_fingerprint
    assert "One match per account" in adapter.fetch(first[0]).body
    assert "Current tier" in adapter.fetch(first[0]).body
    assert adapter.fetch(first[0]).content_type == "text/markdown"
    assert "[Apply](https://example-air.test/match?utm_source=ffb)" in adapter.fetch(
        first[0]
    ).body


def test_catalog_keeps_distinct_action_links_and_discards_known_noise() -> None:
    html = """
        <table data-section="hotel"><tbody>
          <tr><th scope="row">Best Western Rewards</th><td>
            Join <a href="/aarp">AARP</a> and
            <a href="https://bestwestern.test/register">register with Best Western</a>.
          </td></tr>
          <tr><th scope="row">Vietnam Airlines</th><td>
            Use the <a href="https://vietnam.test/match">paid match</a>.
            <a href="https://vietnam.test/match">Full details</a>
          </td></tr>
          <tr><th scope="row">Choice Privileges</th><td>
            <a href="https://choice.test/match">Match details</a>
            <a href="https://wrong.test/marriott"><br></a>
          </td></tr>
          <tr><th scope="row">Enterprise Plus</th><td>
            <a href="https://enterprise.test/match">Full details</a>
            <p><a href="https://enterprise.test/book">Book all your Enterprise rentals here.</a></p>
          </td></tr>
        </tbody></table>
    """
    records = parse_catalog_records(html, "https://catalog.test/status")

    assert records[0].action_urls == (
        "https://catalog.test/aarp",
        "https://bestwestern.test/register",
    )
    assert "[AARP](https://catalog.test/aarp)" in records[0].text
    assert "[register with Best Western](https://bestwestern.test/register)" in records[
        0
    ].text

    assert records[1].action_urls == ("https://vietnam.test/match",)
    assert records[1].text.count("https://vietnam.test/match") == 1
    assert "Full details" in records[1].text

    assert records[2].action_urls == ("https://choice.test/match",)
    assert "wrong.test" not in records[2].text
    assert records[2].discarded_urls == ("https://wrong.test/marriott",)

    assert records[3].action_urls == ("https://enterprise.test/match",)
    assert "enterprise.test/book" not in records[3].text
    assert "Book all your Enterprise rentals" not in records[3].text


def test_statusmatcher_follows_actual_next_link_then_fetches_report_without_identity() -> None:
    index = "https://statusmatcher.com/"
    page_2 = "https://statusmatcher.com/?page=2"
    fetcher = FakeFetcher(
        {
            index: (FIXTURES / "statusmatcher_page_1.html").read_text(),
            page_2: (FIXTURES / "statusmatcher_page_2.html").read_text(),
            "https://statusmatcher.com/report/101": (
                FIXTURES / "statusmatcher_report.html"
            ).read_text(),
        }
    )
    adapter = StatusMatcherAdapter(
        index_url=index, fetcher=fetcher, production_approval=True
    )
    items = adapter.discover()
    assert [item.external_id for item in items] == ["101", "102"]
    assert fetcher.calls == [index, page_2]

    raw = adapter.fetch(items[0])
    assert "Approved from Gold" in raw.body
    assert "Private Person" not in raw.body


def test_statusmatcher_refuses_unapproved_production_collection() -> None:
    adapter = StatusMatcherAdapter(
        index_url="https://statusmatcher.com/", fetcher=FakeFetcher({})
    )
    with pytest.raises(PermissionError):
        adapter.discover()


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


def _gmail_message(message_id: str, recipient: str, sender: str):
    encoded = base64.urlsafe_b64encode(b"A direct status match is open.").decode().rstrip("=")
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["Label_123"],
        "snippet": "status match",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "To", "value": recipient},
                {"name": "From", "value": f"{sender} <news@example.net>"},
                {"name": "Subject", "value": "New match"},
                {"name": "Message-ID", "value": f"<{message_id}@example.net>"},
            ],
            "body": {"data": encoded},
        },
    }


def test_gmail_adapter_enforces_label_and_alias_but_no_sender_allowlist() -> None:
    client = FakeGmailClient()
    adapter = GmailStatusServicesAdapter(client)
    items = adapter.discover()

    assert GMAIL_READONLY_SCOPE.endswith("gmail.readonly")
    assert client.list_args == ("Label_123", QUERY)
    assert [item.external_id for item in items] == ["allowed"]
    assert items[0].raw_metadata["origin_provider"] == "STATUSMATCH"
    assert "direct status match" in adapter.fetch(items[0]).body
