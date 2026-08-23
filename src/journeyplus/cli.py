from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, timedelta

from journeyplus.config import Settings
from journeyplus.db import create_session_factory, engine_from_settings, session_scope
from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.ai.smoke import run_ai_smoke
from journeyplus.automation.service import (
    AutomationLimits,
    automation_status,
    run_daily_cycle,
)
from journeyplus.automation.initialization import (
    run_mail_detail_initialization,
    run_public_initialization_window,
)
from journeyplus.operations import process_pending_documents
from journeyplus.review.api import create_review_app
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.gmail_auth import (
    authorize_gmail,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources
from journeyplus.sources.runtime import build_configured_adapter


SOURCE_IDS = [item.source_id for item in SOURCE_REGISTRY]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journeyplus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed-sources", help="Import or refresh the six sources")
    subparsers.add_parser(
        "gmail-authorize",
        help="Authorize kirikoomiku@gmail.com with gmail.readonly",
    )
    subparsers.add_parser(
        "ai-smoke",
        help="Send one minimal structured request to the configured AI model",
    )
    review = subparsers.add_parser("review-api", help="Run the local internal review API")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", default=8001, type=int)
    collect = subparsers.add_parser("collect", help="Manually collect one source")
    collect.add_argument("source_id", choices=SOURCE_IDS)
    collect.add_argument("--idempotency-key")
    collect.add_argument("--limit", type=_positive_int)
    process = subparsers.add_parser(
        "process-pending",
        help="Process collected documents that lack the current AI classification",
    )
    process.add_argument("--source-id", choices=SOURCE_IDS)
    process.add_argument("--limit", type=_positive_int, default=10)
    run_source = subparsers.add_parser(
        "run-source",
        help="Thin orchestration: collect one source, then process its pending documents",
    )
    run_source.add_argument("source_id", choices=SOURCE_IDS)
    run_source.add_argument("--limit", type=_positive_int, default=10)
    run_source.add_argument("--idempotency-key")
    run_daily = subparsers.add_parser(
        "run-daily",
        help="Run one lease-protected Asia/Shanghai daily automation cycle",
    )
    run_daily.add_argument("--source-item-limit", type=_positive_int)
    run_daily.add_argument("--document-limit", type=_positive_int)
    run_daily.add_argument("--model-call-limit", type=_positive_int)
    subparsers.add_parser(
        "automation-status",
        help="Report daily automation, source, backlog, failure, and review state",
    )
    initialize_mail = subparsers.add_parser(
        "initialize-mail-details",
        help="Expand all current Gmail activity links and wait for source audit",
    )
    initialize_window = subparsers.add_parser(
        "initialize-window",
        help="Run one fixed public-source historical window and wait for audit",
    )
    initialize_window.add_argument("--start", type=_iso_date, required=True)
    initialize_window.add_argument("--end", type=_iso_date, required=True)
    for command in (initialize_mail, initialize_window):
        command.add_argument("--source-item-limit", type=_positive_int)
        command.add_argument("--document-limit", type=_positive_int)
        command.add_argument("--model-call-limit", type=_positive_int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.command == "gmail-authorize":
        account = authorize_gmail(settings)
        print(
            json.dumps(
                {
                    "authorized_account": account,
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_file": settings.gmail_token_file,
                }
            )
        )
        return 0
    if args.command == "ai-smoke":
        result = run_ai_smoke(settings)
        print(result.model_dump_json())
        return 0
    factory = create_session_factory(engine_from_settings(settings))
    if args.command == "review-api":
        import uvicorn

        provider = None
        if settings.ai_base_url and settings.ai_api_key:
            provider = OpenAICompatibleProvider(settings)
        uvicorn.run(
            create_review_app(factory, ai_provider=provider),
            host=args.host,
            port=args.port,
        )
        return 0
    if args.command == "seed-sources":
        with session_scope(factory) as session:
            sources = seed_sources(session)
            print(json.dumps({"seeded": [source.id for source in sources]}))
        return 0
    if args.command == "process-pending":
        provider = OpenAICompatibleProvider(settings)
        summary = process_pending_documents(
            factory,
            provider,
            source_id=args.source_id,
            limit=args.limit,
        )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0
    if args.command == "run-daily":
        provider = OpenAICompatibleProvider(settings)
        summary = run_daily_cycle(
            factory,
            provider,
            lambda source_id: build_configured_adapter(source_id, settings),
            limits=AutomationLimits(
                source_items_per_source=(
                    args.source_item_limit
                    or settings.automation_source_item_limit
                ),
                documents=(
                    args.document_limit or settings.automation_document_limit
                ),
                model_calls=(
                    args.model_call_limit
                    or settings.automation_model_call_limit
                ),
            ),
            lease_duration=timedelta(
                seconds=settings.automation_lease_seconds
            ),
        )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0
    if args.command == "automation-status":
        provider = OpenAICompatibleProvider(settings)
        print(
            json.dumps(
                asdict(automation_status(factory, provider)),
                ensure_ascii=False,
            )
        )
        return 0
    if args.command in {"initialize-mail-details", "initialize-window"}:
        provider = OpenAICompatibleProvider(settings)
        limits = AutomationLimits(
            source_items_per_source=(
                args.source_item_limit
                or max(settings.automation_source_item_limit, 500)
            ),
            documents=args.document_limit or settings.automation_document_limit,
            model_calls=(
                args.model_call_limit or settings.automation_model_call_limit
            ),
        )
        adapter_factory = lambda source_id: build_configured_adapter(
            source_id, settings
        )
        if args.command == "initialize-mail-details":
            summary = run_mail_detail_initialization(
                factory,
                provider,
                adapter_factory,
                limits=limits,
            )
        else:
            summary = run_public_initialization_window(
                factory,
                provider,
                adapter_factory,
                start=args.start,
                end=args.end,
                limits=limits,
            )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0
    provider = (
        OpenAICompatibleProvider(settings) if args.command == "run-source" else None
    )
    with session_scope(factory) as session:
        seed_sources(session)
        adapter = build_configured_adapter(args.source_id, settings)
        collection = collect_manual(
            session,
            adapter,
            idempotency_key=args.idempotency_key,
            max_items=args.limit,
        )
    if args.command == "collect":
        print(json.dumps(asdict(collection), ensure_ascii=False))
        return 0
    assert provider is not None
    processing = process_pending_documents(
        factory,
        provider,
        source_id=args.source_id,
        limit=args.limit,
    )
    print(
        json.dumps(
            {"collection": asdict(collection), "processing": asdict(processing)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
