from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from journeyplus.config import Settings
from journeyplus.db import create_session_factory, engine_from_settings, session_scope
from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.ai.smoke import run_ai_smoke
from journeyplus.review.api import create_review_app
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.gmail import HttpGmailClient
from journeyplus.sources.gmail_auth import (
    authorize_gmail,
    gmail_profile_email,
    load_gmail_access_token,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources


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
    collect.add_argument("source_id", choices=[item.source_id for item in SOURCE_REGISTRY])
    collect.add_argument("--idempotency-key")
    collect.add_argument(
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
    with session_scope(factory) as session:
        if args.command == "seed-sources":
            sources = seed_sources(session)
            print(json.dumps({"seeded": [source.id for source in sources]}))
            return 0
        seed_sources(session)
        gmail_client = None
        if args.source_id == "status_services_mail":
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
        adapter = build_adapter(
            args.source_id,
            gmail_client=gmail_client,
            statusmatcher_approval=args.allow_statusmatcher,
        )
        summary = collect_manual(
            session, adapter, idempotency_key=args.idempotency_key
        )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
