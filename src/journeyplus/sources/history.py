from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.lifecycle.service import BEIJING_TZ
from journeyplus.sources.feed import FeedAdapter


class HistoricalCoverageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalDiscoveryReport:
    pages_scanned: int
    discovered: int
    eligible: int
    missing_published_at: int
    oldest_published_date: str | None
    newest_published_date: str | None


class HistoricalFeedWindowAdapter:
    def __init__(
        self,
        adapter: FeedAdapter,
        *,
        start: date,
        end: date,
        max_pages: int = 50,
    ) -> None:
        if end < start:
            raise ValueError("historical window end precedes start")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.source_id = adapter.source_id
        self._adapter = adapter
        self._start = start
        self._end = end
        self._max_pages = max_pages
        self.report: HistoricalDiscoveryReport | None = None

    def discover(self) -> list[DiscoveredItem]:
        discovered: dict[str, DiscoveredItem] = {}
        seen_pages: set[tuple[str, ...]] = set()
        pages_scanned = 0
        coverage_reached = False
        for page in range(1, self._max_pages + 1):
            items = self._adapter.discover_page(page)
            pages_scanned = page
            if not items:
                coverage_reached = True
                break
            signature = tuple(item.external_id for item in items)
            if signature in seen_pages:
                raise HistoricalCoverageError(
                    f"{self.source_id} feed pagination repeated page {page}"
                )
            seen_pages.add(signature)
            for item in items:
                discovered.setdefault(item.external_id, item)
            dates = [
                item.published_at.astimezone(BEIJING_TZ).date()
                for item in items
                if item.published_at is not None
            ]
            if dates and min(dates) < self._start:
                coverage_reached = True
                break
        dated_items = [
            item for item in discovered.values() if item.published_at is not None
        ]
        local_dates = [
            item.published_at.astimezone(BEIJING_TZ).date()
            for item in dated_items
            if item.published_at is not None
        ]
        eligible = [
            item
            for item in dated_items
            if self._start
            <= item.published_at.astimezone(BEIJING_TZ).date()
            <= self._end
        ]
        self.report = HistoricalDiscoveryReport(
            pages_scanned=pages_scanned,
            discovered=len(discovered),
            eligible=len(eligible),
            missing_published_at=len(discovered) - len(dated_items),
            oldest_published_date=min(local_dates).isoformat() if local_dates else None,
            newest_published_date=max(local_dates).isoformat() if local_dates else None,
        )
        if not coverage_reached:
            raise HistoricalCoverageError(
                f"{self.source_id} did not reach dates before {self._start.isoformat()} "
                f"within {self._max_pages} feed pages"
            )
        return sorted(
            eligible,
            key=lambda item: (item.published_at, item.external_id),
        )

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        return self._adapter.fetch(item)
