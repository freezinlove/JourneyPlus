from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser

from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher


class FeedAdapter:
    def __init__(
        self,
        *,
        source_id: str,
        feed_url: str,
        content_strategy: str,
        fetcher: Fetcher,
        extra_drop_params: set[str] | None = None,
        incremental_baseline_date: str | date | None = None,
        incremental_timezone: str = "Asia/Shanghai",
        incremental_max_pages: int = 100,
    ) -> None:
        self.source_id = source_id
        self.feed_url = feed_url
        self.content_strategy = content_strategy
        self._fetcher = fetcher
        self._extra_drop_params = extra_drop_params or set()
        self._incremental_baseline_date = _optional_date(
            incremental_baseline_date
        )
        self._incremental_timezone = ZoneInfo(incremental_timezone)
        if incremental_max_pages < 1:
            raise ValueError("incremental_max_pages must be positive")
        self._incremental_max_pages = incremental_max_pages
        self._incremental_cursor: str | None = None
        self._incremental_configured = False
        self._observed_head_external_id: str | None = None

    def configure_feed_incremental_discovery(
        self, *, discovery_cursor: str | None
    ) -> None:
        self._incremental_cursor = discovery_cursor
        self._incremental_configured = True

    def discover(self) -> list[DiscoveredItem]:
        if (
            self._incremental_baseline_date is not None
            and self._incremental_configured
        ):
            return self._discover_incremental()
        return self.discover_page(1)

    def discovery_cursor_after_collection(
        self,
        *,
        considered_items: list[DiscoveredItem],
        fully_considered: bool,
    ) -> str | None:
        if not self._incremental_configured:
            return None
        if fully_considered:
            return self._observed_head_external_id or self._incremental_cursor
        if considered_items:
            # Incremental discovery is returned oldest-first. Advancing only to the
            # newest item actually processed preserves the unprocessed suffix.
            return considered_items[-1].external_id
        return self._incremental_cursor

    def _discover_incremental(self) -> list[DiscoveredItem]:
        results: list[DiscoveredItem] = []
        seen_external_ids: set[str] = set()
        page_signatures: set[tuple[str, ...]] = set()
        boundary_reached = False
        self._observed_head_external_id = None

        for page in range(1, self._incremental_max_pages + 1):
            page_items = self.discover_page(page)
            if not page_items:
                boundary_reached = True
                break
            signature = tuple(item.external_id for item in page_items)
            if signature in page_signatures:
                raise RuntimeError(
                    "Feed pagination repeated a page before reaching the "
                    "incremental boundary"
                )
            page_signatures.add(signature)
            if self._observed_head_external_id is None:
                self._observed_head_external_id = page_items[0].external_id

            for item in page_items:
                if item.external_id == self._incremental_cursor:
                    boundary_reached = True
                    break
                if item.external_id in seen_external_ids:
                    continue
                seen_external_ids.add(item.external_id)
                if self._incremental_cursor is None and not self._after_baseline(item):
                    boundary_reached = True
                    break
                results.append(item)
            if boundary_reached:
                break

        if not boundary_reached:
            raise RuntimeError(
                "Feed incremental boundary was not reached within "
                f"{self._incremental_max_pages} pages"
            )

        # Oldest-first makes a collection limit safe: every successful partial run
        # advances a contiguous boundary without skipping newer discoveries.
        results.reverse()
        return results

    def _after_baseline(self, item: DiscoveredItem) -> bool:
        published_at = item.published_at
        if published_at is None:
            return True
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        assert self._incremental_baseline_date is not None
        return (
            published_at.astimezone(self._incremental_timezone).date()
            > self._incremental_baseline_date
        )

    def discover_page(self, page: int) -> list[DiscoveredItem]:
        if page < 1:
            raise ValueError("feed page must be positive")
        feed_url = _feed_page_url(self.feed_url, page)
        response = self._fetcher.get(feed_url)
        parsed = feedparser.parse(response.body)
        results: list[DiscoveredItem] = []
        for entry in parsed.entries:
            link = str(entry.get("link") or "").strip()
            if not link:
                continue
            canonical = canonicalize_url(link, extra_drop=self._extra_drop_params)
            external_id = str(entry.get("id") or entry.get("guid") or canonical)
            feed_body = self._feed_body(entry)
            discovery_signature = "\n".join(
                (
                    external_id,
                    canonical,
                    str(entry.get("title") or ""),
                    str(entry.get("published") or entry.get("updated") or ""),
                    feed_body,
                )
            )
            results.append(
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id=external_id,
                    discovered_url=link,
                    canonical_url=canonical,
                    title=str(entry.get("title") or ""),
                    published_at=_published_at(entry),
                    discovery_fingerprint=hashlib.sha256(
                        discovery_signature.encode()
                    ).hexdigest(),
                    raw_metadata={
                        "feed_url": feed_url,
                        "feed_guid": str(entry.get("id") or entry.get("guid") or ""),
                        "feed_summary": str(entry.get("summary") or ""),
                        "feed_body": feed_body,
                        "content_strategy": self.content_strategy,
                    },
                )
            )
        return results

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        if self.content_strategy == "fetch_article":
            response = self._fetcher.get(item.canonical_url)
            canonical_url = canonicalize_url(
                response.final_url, extra_drop=self._extra_drop_params
            )
            body = response.body
            content_type = response.content_type
        else:
            canonical_url = item.canonical_url
            body = str(item.raw_metadata.get("feed_body") or "")
            content_type = "text/html"
        if not body.strip():
            raise ValueError(f"Feed item {item.external_id} has no usable body")
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=canonical_url,
            body=body,
            content_type=content_type,
            metadata={
                "feed_url": self.feed_url,
                "content_strategy": self.content_strategy,
                "title": item.title,
            },
        )

    @staticmethod
    def _feed_body(entry: Any) -> str:
        content = entry.get("content") or []
        if content:
            return str(content[0].get("value") or "")
        return str(entry.get("summary") or entry.get("description") or "")


def _published_at(entry: Any) -> datetime | None:
    value = entry.get("published") or entry.get("updated")
    if not value:
        return None
    try:
        result = parsedate_to_datetime(str(value))
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _feed_page_url(feed_url: str, page: int) -> str:
    if page == 1:
        return feed_url
    parsed = urlsplit(feed_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["paged"] = str(page)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )
