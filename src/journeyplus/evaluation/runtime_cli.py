from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings
from journeyplus.evaluation.runtime import run_gold_baseline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journeyplus-gold-run")
    parser.add_argument("gold", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/runs/status_opportunity_phase1_v1-current"),
    )
    parser.add_argument("--label", default="current")
    parser.add_argument("--max-documents", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    freeze_path = args.freeze or args.gold.with_suffix(".freeze.json")
    provider = OpenAICompatibleProvider(Settings.from_env())

    def progress(
        current: int,
        total: int,
        document_key: str,
        label: str,
        event_count: int,
    ) -> None:
        print(
            f"[{current}/{total}] {document_key} -> {label} "
            f"events={event_count}",
            flush=True,
        )

    result = run_gold_baseline(
        provider=provider,
        gold_path=args.gold,
        freeze_path=freeze_path,
        output_dir=args.output_dir,
        label=args.label,
        max_documents=args.max_documents,
        progress=progress,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.complete or args.max_documents else 1


if __name__ == "__main__":
    raise SystemExit(main())
