from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from journeyplus.contracts import DiscoveredItem, RawDocument


@dataclass(frozen=True, slots=True)
class FetchResponse:
    body: str
    content_type: str
    final_url: str


class Fetcher(Protocol):
    def get(self, url: str) -> FetchResponse: ...


class SourceAdapter(Protocol):
    source_id: str

    def discover(self) -> list[DiscoveredItem]: ...

    def fetch(self, item: DiscoveredItem) -> RawDocument: ...


class HttpxFetcher:
    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "JourneyPlus/0.1 (+manual collection)"},
        )

    def get(self, url: str) -> FetchResponse:
        response = self._client.get(url)
        response.raise_for_status()
        return FetchResponse(
            body=response.text,
            content_type=response.headers.get("content-type", "text/html").split(";", 1)[0],
            final_url=str(response.url),
        )

