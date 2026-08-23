from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence

from journeyplus.content.cleaner import lightly_clean
from journeyplus.sources.factory import build_adapter


PUBLIC_SOURCE_IDS = (
    "ffb_elite_status_feed",
    "awardwallet_elite_status_feed",
    "loyaltylobby_feed",
    "frequentmiler_elite_status_feed",
    "verylvke_feed",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only, non-persistent smoke test for public V1 sources."
    )
    parser.add_argument("source_ids", nargs="*", choices=PUBLIC_SOURCE_IDS)
    args = parser.parse_args(argv)
    source_ids = tuple(args.source_ids) or PUBLIC_SOURCE_IDS
    results = []
    for source_id in source_ids:
        started = time.monotonic()
        try:
            adapter = build_adapter(source_id)
            items = adapter.discover()
            if not items:
                raise ValueError("No source items were discovered")
            first = items[0]
            raw = adapter.fetch(first)
            normalized = lightly_clean(raw)
            if not normalized.normalized_body:
                raise ValueError("The first document became empty after light cleaning")
            results.append(
                {
                    "source_id": source_id,
                    "status": "PASS",
                    "discovered_count": len(items),
                    "first_title": first.title,
                    "first_url": first.canonical_url,
                    "first_body_characters": len(raw.body),
                    "first_normalized_characters": len(
                        normalized.normalized_body
                    ),
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "source_id": source_id,
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                }
            )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(item["status"] == "FAIL" for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
