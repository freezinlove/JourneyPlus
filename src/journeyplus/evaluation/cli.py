from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from journeyplus.evaluation.evaluator import evaluate
from journeyplus.evaluation.schema import GoldDataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journeyplus-eval")
    parser.add_argument("gold", type=Path)
    parser.add_argument(
        "--prediction",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="Repeat to compare current and candidate model/prompt outputs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gold = GoldDataset.model_validate_json(args.gold.read_text())
    reports = []
    for configured in args.prediction:
        try:
            label, path = configured.split("=", 1)
        except ValueError as exc:
            raise SystemExit("--prediction must be LABEL=PATH") from exc
        prediction = GoldDataset.model_validate_json(Path(path).read_text())
        reports.append(evaluate(gold, prediction, label=label).as_dict())
    print(
        json.dumps(
            {
                "gold_dataset_version": gold.dataset_version,
                "reports": reports,
                "note": "No fixed quality thresholds are assumed before the human baseline exists.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

