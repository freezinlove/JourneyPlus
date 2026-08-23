from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from journeyplus.config import Settings
from journeyplus.content.service import IngestionService
from journeyplus.contracts import DiscoveredItem
from journeyplus.db import create_session_factory, engine_from_settings, session_scope
from journeyplus.sources.base import SourceAdapter
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.registry import seed_sources


@dataclass(frozen=True, slots=True)
class RealLifecycleCase:
    key: str
    source_id: str
    url: str
    boundary: str


CASES: tuple[RealLifecycleCase, ...] = (
    RealLifecycleCase(
        key="united_2025_initial_deadline",
        source_id="ffb_elite_status_feed",
        url=(
            "https://blog.frequentflyerbonuses.com/2025/01/"
            "january-17-2025-highlight.html"
        ),
        boundary="明确的旧截止日；与后续文章组成延期链",
    ),
    RealLifecycleCase(
        key="united_2025_explicit_extension",
        source_id="ffb_elite_status_feed",
        url=(
            "https://blog.frequentflyerbonuses.com/2025/08/"
            "august-27-2025-highlight.html"
        ),
        boundary="正文写明 OFFER EXTENDED，截止日从 2025-06-30 延至 2025-12-31",
    ),
    RealLifecycleCase(
        key="gha_2025_period",
        source_id="ffb_elite_status_feed",
        url=(
            "https://blog.frequentflyerbonuses.com/2025/09/"
            "gha-discovery-status-match-2025.html"
        ),
        boundary="2025 独立期次，截止日 2025-11-30",
    ),
    RealLifecycleCase(
        key="gha_2026_new_period",
        source_id="ffb_elite_status_feed",
        url=(
            "https://blog.frequentflyerbonuses.com/2026/03/"
            "gha-discovery-status-match.html"
        ),
        boundary="正文明确 returned for the first time in 2026，非延期新一期",
    ),
    RealLifecycleCase(
        key="frontier_2025_gold",
        source_id="awardwallet_elite_status_feed",
        url="https://awardwallet.com/news/airlines/frontier-status-match/",
        boundary="仅日期截止日 2025-09-09，当前应过期",
    ),
    RealLifecycleCase(
        key="frontier_2025_platinum",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/news/airlines/"
            "frontier-elite-status-promotion/"
        ),
        boundary=(
            "同品牌后续不同机制；顶部已结束与原截止日 2025-12-31 "
            "并存，应独立且保守 UNKNOWN"
        ),
    ),
    RealLifecycleCase(
        key="jetblue_2025_dunkin",
        source_id="awardwallet_elite_status_feed",
        url="https://awardwallet.com/blog/jetblue-dunkin-status-promotion/",
        boundary="活动提前结束；正文仍含原计划日期，不能当作常驻匹配",
    ),
    RealLifecycleCase(
        key="jetblue_2025_25_for_25",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/news/jetblue-trueblue/"
            "25-for-25-challenge/"
        ),
        boundary="与 Dunkin 活动窗口重叠但获取机制不同",
    ),
    RealLifecycleCase(
        key="jetblue_2026_standing_match",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/airlines/jetblue-trueblue/"
            "jetblue-status-match/"
        ),
        boundary="当前开放但没有申请截止日，应保持 UNKNOWN",
    ),
    RealLifecycleCase(
        key="jetblue_2026_est_deadline",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/news/jetblue-trueblue/"
            "buy-jetblue-tiles/"
        ),
        boundary=(
            "明确 2026-05-28 11:59 p.m. EST，须换算北京时间而非按本地日末"
        ),
    ),
    RealLifecycleCase(
        key="delta_2026_active",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/airlines/delta-skymiles/"
            "delta-status-match/"
        ),
        boundary="当前开放，明确截止日 2026-12-31，应为 ACTIVE",
    ),
    RealLifecycleCase(
        key="alaska_2026_no_deadline",
        source_id="awardwallet_elite_status_feed",
        url=(
            "https://awardwallet.com/airlines/alaska-atmos-rewards/"
            "alaska-status-match/"
        ),
        boundary="只有挑战期和会籍有效期，没有申请截止日，应保持 UNKNOWN",
    ),
)


class ExactArticleAdapter:
    def __init__(self, case: RealLifecycleCase) -> None:
        self.source_id = case.source_id
        self._case = case
        self._delegate: SourceAdapter = build_adapter(case.source_id)

    def discover(self) -> list[DiscoveredItem]:
        fingerprint = hashlib.sha256(self._case.url.encode()).hexdigest()
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=f"real-lifecycle:{self._case.key}",
                discovered_url=self._case.url,
                canonical_url=self._case.url,
                title=self._case.key,
                discovery_fingerprint=fingerprint,
                raw_metadata={
                    "validation_case": self._case.key,
                    "boundary": self._case.boundary,
                },
            )
        ]

    def fetch(self, item: DiscoveredItem):
        return self._delegate.fetch(item)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch selected public real-world lifecycle cases without storing "
            "their bodies in the repository."
        )
    )
    parser.add_argument(
        "case_keys",
        nargs="*",
        choices=tuple(item.key for item in CASES),
    )
    args = parser.parse_args(argv)
    selected = [
        item for item in CASES if not args.case_keys or item.key in args.case_keys
    ]
    settings = Settings.from_env()
    factory = create_session_factory(engine_from_settings(settings))
    results: list[dict[str, object]] = []
    with session_scope(factory) as session:
        seed_sources(session)
        ingestion = IngestionService(session)
        for case in selected:
            adapter = ExactArticleAdapter(case)
            item = adapter.discover()[0]
            if not ingestion.should_fetch(item):
                results.append(
                    {
                        **asdict(case),
                        "new_version": False,
                        "document_version_id": None,
                    }
                )
                continue
            ingested = ingestion.ingest(item, adapter.fetch(item))
            results.append(
                {
                    **asdict(case),
                    "new_version": ingested.new_version,
                    "document_version_id": str(ingested.document_version.id),
                    "normalized_characters": len(
                        ingested.document_version.normalized_body
                    ),
                }
            )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
