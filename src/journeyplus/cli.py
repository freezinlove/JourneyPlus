from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta

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
from journeyplus.article_operations import (
    GENERIC_PUBLIC_SOURCE_ID,
    archive_article_mapping,
    extend_article_mapping,
    process_pending_articles,
    restore_article_mapping,
)
from journeyplus.operations import process_pending_documents
from journeyplus.review.api import create_review_app
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.gmail_auth import (
    authorize_gmail,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources
from journeyplus.sources.runtime import build_configured_adapter
from journeyplus.statusmatch.audit import audit_statusmatch_projects
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.membership.contracts import UnifiedTraversalLimits
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.statusmatch.article_workflow import (
    process_pending_statusmatch_articles,
)
from journeyplus.statusmatch.articles import (
    discover_statusmatch_article_routes,
    prepare_statusmatch_article_projects,
)
from journeyplus.statusmatch.composed_brief import composed_statusmatch_brief
from journeyplus.statusmatch.project_workflow import (
    process_pending_statusmatch_projects,
)
from journeyplus.sources.base import HttpxFetcher


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


def _iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO 8601 datetime") from exc


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
    article_archive = subparsers.add_parser(
        "article-mapping-archive",
        help="Soft-archive one ordinary article mapping contribution",
    )
    article_archive.add_argument("opportunity_id")
    article_archive.add_argument("--reason", required=True)
    article_archive.add_argument("--actor", default="operator")
    article_restore = subparsers.add_parser(
        "article-mapping-restore",
        help="Restore an ordinary article mapping contribution",
    )
    article_restore.add_argument("opportunity_id")
    article_restore.add_argument("--visibility-until", type=_iso_datetime)
    article_restore.add_argument("--reason", required=True)
    article_restore.add_argument("--actor", default="operator")
    article_extend = subparsers.add_parser(
        "article-mapping-extend",
        help="Extend an ordinary article mapping contribution to a future time",
    )
    article_extend.add_argument("opportunity_id")
    article_extend.add_argument("visibility_until", type=_iso_datetime)
    article_extend.add_argument("--reason", required=True)
    article_extend.add_argument("--actor", default="operator")
    statusmatch_audit = subparsers.add_parser(
        "statusmatch-audit",
        help="Refresh and audit selected managed StatusMatch projects",
    )
    statusmatch_audit.add_argument("hosts", nargs="+")
    statusmatch_audit.add_argument(
        "--no-refresh",
        action="store_true",
        help="Audit the stored current snapshot without fetching public pages",
    )
    statusmatch_graph = subparsers.add_parser(
        "statusmatch-graph",
        help="Expand a current membership as a bounded unified membership tree",
    )
    statusmatch_graph.add_argument("program")
    statusmatch_graph.add_argument("tier")
    statusmatch_graph.add_argument("--max-depth", type=_positive_int, default=4)
    statusmatch_graph.add_argument("--max-nodes", type=_positive_int, default=100)
    statusmatch_graph.add_argument("--max-branches", type=_positive_int, default=20)
    subparsers.add_parser(
        "statusmatch-graph-audit",
        help="Audit current StatusMatch graph fidelity and topology",
    )
    subparsers.add_parser(
        "membership-graph-audit",
        help="Audit the unified official and ordinary-article membership graph",
    )
    statusmatch_articles = subparsers.add_parser(
        "statusmatch-articles",
        help="Discover, prepare, and process third-party StatusMatch-linked articles",
    )
    statusmatch_articles.add_argument("--source-id", choices=SOURCE_IDS)
    statusmatch_articles.add_argument("--limit", type=_positive_int, default=20)
    statusmatch_brief = subparsers.add_parser(
        "statusmatch-brief",
        help="Read an official StatusMatch brief with current third-party highlights",
    )
    statusmatch_brief.add_argument("host")
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
    if args.command in {
        "article-mapping-archive",
        "article-mapping-restore",
        "article-mapping-extend",
    }:
        with session_scope(factory) as session:
            if args.command == "article-mapping-archive":
                result = archive_article_mapping(
                    session,
                    opportunity_id=args.opportunity_id,
                    reason=args.reason,
                    actor=args.actor,
                )
            elif args.command == "article-mapping-restore":
                result = restore_article_mapping(
                    session,
                    opportunity_id=args.opportunity_id,
                    visibility_until_at=args.visibility_until,
                    reason=args.reason,
                    actor=args.actor,
                )
            else:
                result = extend_article_mapping(
                    session,
                    opportunity_id=args.opportunity_id,
                    visibility_until_at=args.visibility_until,
                    reason=args.reason,
                    actor=args.actor,
                )
            print(
                json.dumps(
                    {
                        "opportunity_id": str(result.id),
                        "visibility_until_at": result.visibility_until_at.isoformat(),
                        "visibility_policy": result.visibility_policy,
                        "archived_at": (
                            result.archived_at.isoformat()
                            if result.archived_at is not None
                            else None
                        ),
                        "archive_reason": result.archive_reason,
                    }
                )
            )
        return 0
    if args.command == "statusmatch-graph":
        limits = UnifiedTraversalLimits(
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
            max_branches=args.max_branches,
        )
        with session_scope(factory) as session:
            result = UnifiedMembershipTreeService(session).tree(
                args.program,
                args.tier,
                limits=limits,
            )
            print(result.model_dump_json())
        return 0
    if args.command == "membership-graph-audit":
        with session_scope(factory) as session:
            result = UnifiedMembershipTreeService(session).audit()
            print(result.model_dump_json())
        return 0
    if args.command == "statusmatch-graph-audit":
        with session_scope(factory) as session:
            result = MembershipGraphService(session).audit()
            print(result.model_dump_json())
        return 0
    if args.command == "statusmatch-brief":
        with session_scope(factory) as session:
            result = composed_statusmatch_brief(session, host=args.host)
            print(result.model_dump_json())
        return 0
    if args.command == "statusmatch-articles":
        provider = OpenAICompatibleProvider(settings)
        source_ids = [args.source_id] if args.source_id else None
        with session_scope(factory) as session:
            discovery = discover_statusmatch_article_routes(
                session, source_ids=source_ids
            )
            preparation = prepare_statusmatch_article_projects(
                session,
                HttpxFetcher(),
                hosts=list(discovery.project_hosts),
            )
        projects = process_pending_statusmatch_projects(
            factory,
            provider,
            hosts=list(discovery.project_hosts) or None,
            limit=args.limit,
        )
        articles = process_pending_statusmatch_articles(
            factory,
            provider,
            hosts=list(discovery.project_hosts) or None,
            limit=args.limit,
        )
        print(
            json.dumps(
                {
                    "discovery": asdict(discovery),
                    "preparation": asdict(preparation),
                    "official_projects": asdict(projects),
                    "articles": asdict(articles),
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "process-pending":
        if args.source_id not in {None, GENERIC_PUBLIC_SOURCE_ID}:
            parser.error("通用 V2 链路当前只开放 loyaltylobby_feed")
        provider = OpenAICompatibleProvider(settings)
        summary = (
            process_pending_documents(
                factory,
                provider,
                source_id=GENERIC_PUBLIC_SOURCE_ID,
                limit=args.limit,
            )
            if settings.generic_article_pipeline == "v1"
            else process_pending_articles(
                factory,
                provider,
                limit=args.limit,
                title_drop_enabled=settings.generic_title_drop_enabled,
            )
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
            generic_pipeline_mode=settings.generic_article_pipeline,
            generic_title_drop_enabled=settings.generic_title_drop_enabled,
        )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0
    if args.command == "automation-status":
        provider = OpenAICompatibleProvider(settings)
        print(
            json.dumps(
                asdict(
                    automation_status(
                        factory,
                        provider,
                        generic_title_drop_enabled=(
                            settings.generic_title_drop_enabled
                        ),
                    )
                ),
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "statusmatch-audit":
        provider = OpenAICompatibleProvider(settings)
        print(
            json.dumps(
                audit_statusmatch_projects(
                    factory,
                    provider,
                    hosts=args.hosts,
                    refresh=not args.no_refresh,
                ),
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
    if args.source_id != GENERIC_PUBLIC_SOURCE_ID:
        parser.error("通用 V2 链路当前只开放 loyaltylobby_feed")
    processing = (
        process_pending_documents(
            factory,
            provider,
            source_id=GENERIC_PUBLIC_SOURCE_ID,
            limit=args.limit,
        )
        if settings.generic_article_pipeline == "v1"
        else process_pending_articles(
            factory,
            provider,
            limit=args.limit,
            title_drop_enabled=settings.generic_title_drop_enabled,
        )
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
