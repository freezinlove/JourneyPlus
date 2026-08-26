from __future__ import annotations

from urllib.parse import urlsplit

from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher


class SinglePageAdapter:
    def __init__(
        self,
        *,
        source_id: str,
        page_url: str,
        external_id: str,
        content_strategy: str,
        fetcher: Fetcher,
        title: str = "",
    ) -> None:
        self.source_id = source_id
        self.page_url = canonicalize_url(page_url)
        self.external_id = external_id
        self.content_strategy = content_strategy
        self.title = title
        self._fetcher = fetcher

    def discover(self) -> list[DiscoveredItem]:
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=self.external_id,
                discovered_url=self.page_url,
                canonical_url=self.page_url,
                title=self.title,
                raw_metadata={
                    "content_strategy": self.content_strategy,
                    "refresh_on_discovery": True,
                },
            )
        ]

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        if item.source_id != self.source_id or item.external_id != self.external_id:
            raise ValueError("Single-page item identity does not match adapter")
        response = self._fetcher.get(self.page_url)
        final_url = canonicalize_url(response.final_url)
        if _origin_and_path(final_url) != _origin_and_path(self.page_url):
            raise ValueError(
                f"Single-page fetch left the configured URL: {final_url}"
            )
        if not response.body.strip():
            raise ValueError("Single-page response body is empty")
        return RawDocument(
            source_id=self.source_id,
            external_id=self.external_id,
            canonical_url=final_url,
            body=response.body,
            content_type=response.content_type,
            metadata={
                "content_strategy": self.content_strategy,
                "title": item.title,
                "page_url": self.page_url,
            },
        )


def _origin_and_path(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.path.rstrip("/")

