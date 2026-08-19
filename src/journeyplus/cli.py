from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from journeyplus.config import Settings
from journeyplus.db import create_session_factory, engine_from_settings, session_scope
from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.ai.smoke import run_ai_smoke
from journeyplus.operations import process_pending_documents
from journeyplus.review.api import create_review_app
from journeyplus.sources.base import SourceAdapter
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.gmail import HttpGmailClient
from journeyplus.sources.gmail_auth import (
    authorize_gmail,
    gmail_profile_email,
    load_gmail_access_token,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources


SOURCE_IDS = [item.source_id for item in SOURCE_REGISTRY]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="journeyplus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed-sources", help="Import or refresh the eight V1 sources")
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
    collect.add_argument(
        "--allow-statusmatcher",
        action="store_true",
        help="Confirm production access approval was completed",
    )
    process = subparsers.add_parser(
        "process-pending",
        help="Process already collected documents that lack current AI analysis",
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
    run_source.add_argument(
        "--allow-statusmatcher",
        action="store_true",
        help="Confirm production access approval was completed",
    )
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
    provider = (
        OpenAICompatibleProvider(settings) if args.command == "run-source" else None
    )
    with session_scope(factory) as session:
        seed_sources(session)
        adapter = _build_configured_adapter(
            args.source_id,
            settings,
            allow_statusmatcher=args.allow_statusmatcher,
        )
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


def _build_configured_adapter(
    source_id: str,
    settings: Settings,
    *,
    allow_statusmatcher: bool,
) -> SourceAdapter:
    gmail_client = None
    if source_id == "status_services_mail":
        access_token = settings.gmail_access_token
        if access_token:
            account = gmail_profile_email(access_token)
            if account.casefold() != "kirikoomiku@gmail.com":
                raise SystemExit(
                    f"Authorized Gmail account is {account}, expected "
                    "kirikoomiku@gmail.com"
                )
        else:
            access_token = load_gmail_access_token(settings)
        gmail_client = HttpGmailClient(access_token)
    return build_adapter(
        source_id,
        gmail_client=gmail_client,
        statusmatcher_approval=allow_statusmatcher,
    )


if __name__ == "__main__":
    raise SystemExit(main())
