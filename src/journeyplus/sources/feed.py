from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

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
    ) -> None:
        self.source_id = source_id
        self.feed_url = feed_url
        self.content_strategy = content_strategy
        self._fetcher = fetcher
        self._extra_drop_params = extra_drop_params or set()

    def discover(self) -> list[DiscoveredItem]:
        response = self._fetcher.get(self.feed_url)
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
                        "feed_url": self.feed_url,
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
