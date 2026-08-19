from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher


_REPORT_PATTERN = re.compile(r"/report/(\d+)(?:$|[/?#])")


class StatusMatcherAdapter:
    source_id = "statusmatcher_reports"

    def __init__(
        self,
        *,
        index_url: str,
        fetcher: Fetcher,
        production_approval: bool = False,
        max_pages: int = 100,
    ) -> None:
        self.index_url = index_url
        self._fetcher = fetcher
        self._production_approval = production_approval
        self._max_pages = max_pages

    def discover(self) -> list[DiscoveredItem]:
        if not self._production_approval:
            raise PermissionError("StatusMatcher production collection requires approval")
        found: dict[str, DiscoveredItem] = {}
        page_url: str | None = self.index_url
        visited: set[str] = set()
        while page_url and len(visited) < self._max_pages:
            canonical_page = canonicalize_url(page_url)
            if canonical_page in visited:
                break
            visited.add(canonical_page)
            response = self._fetcher.get(page_url)
            tree = HTMLParser(response.body)
            for link in tree.css("a[href]"):
                absolute = urljoin(response.final_url, link.attributes["href"])
                match = _REPORT_PATTERN.search(absolute)
                if not match:
                    continue
                report_id = match.group(1)
                canonical = canonicalize_url(absolute)
                found.setdefault(
                    report_id,
                    DiscoveredItem(
                        source_id=self.source_id,
                        external_id=report_id,
                        discovered_url=absolute,
                        canonical_url=canonical,
                        title=link.text(separator=" ", strip=True) or f"Report {report_id}",
                        raw_metadata={"index_page": canonical_page},
                    ),
                )
            page_url = _next_page(tree, response.final_url)
        return list(found.values())

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        if not self._production_approval:
            raise PermissionError("StatusMatcher production collection requires approval")
        response = self._fetcher.get(item.canonical_url)
        body = _remove_identity_nodes(response.body)
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=canonicalize_url(response.final_url),
            body=body,
            content_type=response.content_type,
            storage_mode="minimal_snapshot",
            metadata={"identity_removed": True, "user_submitted": True},
        )


def _next_page(tree: HTMLParser, base_url: str) -> str | None:
    for link in tree.css("a[href]"):
        label = link.text(separator=" ", strip=True).casefold()
        rel = link.attributes.get("rel", "").casefold()
        if "next" in rel or label in {"next", "next ›", "older", "下一页"}:
            return urljoin(base_url, link.attributes["href"])
    return None


def _remove_identity_nodes(html: str) -> str:
    tree = HTMLParser(html)
    for selector in (".username", ".user-name", "[data-user]", "[itemprop='author']"):
        for node in tree.css(selector):
            node.decompose()
    return tree.html

