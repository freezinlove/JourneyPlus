from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.agent.contracts import WaitCheckStatus, WaitCheckSummary
from journeyplus.agent.controller import (
    AgentController,
    ExperienceResearcher,
    cleanup_expired_interactions,
)
from journeyplus.agent.waiting import WaitGoalService
from journeyplus.article_operations import (
    GENERIC_PUBLIC_SOURCE_ID,
    pending_article_count,
    process_pending_articles,
)
from journeyplus.article_pipeline.lifecycle import advance_article_lifecycles
from journeyplus.buy_points.operations import (
    BuyPointsProcessingSummary,
    pending_buy_points_count,
    process_pending_buy_points,
)
from journeyplus.buy_points.service import BUY_POINTS_SOURCE_ID
from journeyplus.contracts import DocumentLabel, RunStatus
from journeyplus.lifecycle.service import BEIJING_TZ, advance_lifecycles
from journeyplus.models import (
    AutomationLease,
    AutomationRun,
    CollectionRun,
    FactSetRecord,
    JobRun,
    ArticleAnalysisRecord,
    DocumentVersion,
    Source,
    SourceAutomationState,
    SourceItem,
    StatusEvent,
)
from journeyplus.operations import (
    pending_document_count,
    process_pending_documents,
)
from journeyplus.sources.base import Fetcher, HttpxFetcher, SourceAdapter
from journeyplus.sources.collection import (
    automatically_scheduled_source_ids,
)
from journeyplus.sources.registry import SOURCE_REGISTRY, seed_sources
from journeyplus.statusmatch.service import (
    StatusMatchMonitoringSummary,
)
from journeyplus.statusmatch.article_workflow import (
    StatusMatchArticleProcessingSummary,
    pending_statusmatch_article_count,
    process_pending_statusmatch_articles,
)
from journeyplus.statusmatch.articles import (
    ArticleProjectPreparationSummary,
    ArticleRouteDiscoverySummary,
    discover_statusmatch_article_routes,
)
from journeyplus.statusmatch.project_workflow import (
    StatusMatchProjectProcessingSummary,
    process_pending_statusmatch_projects,
)


LEASE_NAME = "daily-source-automation"


@dataclass(frozen=True, slots=True)
class AutomationLimits:
    source_items_per_source: int = 100
    documents: int = 20
    model_calls: int = 100

    def __post_init__(self) -> None:
        if min(
            self.source_items_per_source,
            self.documents,
            self.model_calls,
        ) < 1:
            raise ValueError("automation limits must be positive")


@dataclass(frozen=True, slots=True)
class SourceCycleSummary:
    source_id: str
    status: str
    discovered: int = 0
    considered: int = 0
    new_documents: int = 0
    reused: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DailyCycleSummary:
    run_id: str | None
    day_bucket: str
    status: str
    skipped: bool
    skip_reason: str | None
    error: str | None
    sources: tuple[SourceCycleSummary, ...]
    documents_selected: int
    documents_succeeded: int
    documents_failed: int
    model_calls: int
    generic_title_model_calls: int
    generic_interpretation_model_calls: int
    generic_brief_model_calls: int
    buy_points_selected: int
    buy_points_succeeded: int
    buy_points_failed: int
    buy_points_reused: int
    buy_points_latest_offer_count: int
    buy_points_diagnostics: tuple[str, ...]
    lifecycle_scanned: int
    lifecycle_updated: int
    lifecycle_expired: int
    statusmatch_projects_checked: int
    statusmatch_pages_checked: int
    statusmatch_pages_changed: int
    statusmatch_projects_archived: int
    statusmatch_errors: tuple[str, ...]
    statusmatch_projects_selected: int
    statusmatch_projects_succeeded: int
    statusmatch_projects_failed: int
    statusmatch_project_model_calls: int
    statusmatch_project_errors: tuple[str, ...]
    statusmatch_project_outputs: tuple[dict[str, Any], ...]
    statusmatch_article_routes_created: int
    statusmatch_article_hosts_fetched: tuple[str, ...]
    statusmatch_articles_selected: int
    statusmatch_articles_succeeded: int
    statusmatch_articles_failed: int
    statusmatch_article_model_calls: int
    statusmatch_article_errors: tuple[str, ...]
    statusmatch_article_outputs: tuple[dict[str, Any], ...]
    agent_wait_status: str
    agent_wait_matching_count: int
    agent_wait_model_called: bool
    agent_wait_error: str | None
    backlog_count: int
    needs_review_count: int
    knowledge_outputs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class SourceStatusSummary:
    source_id: str
    enabled: bool
    automatic_scheduling: bool
    collection_cadence: str | None
    last_day_bucket: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    last_failure_at: str | None
    last_error: str | None
    consecutive_failures: int
    last_new_document_count: int
    pending_document_count: int


@dataclass(frozen=True, slots=True)
class AutomationStatusSummary:
    lease_owner: str | None
    lease_expires_at: str | None
    last_run_id: str | None
    last_run_day: str | None
    last_run_status: str | None
    last_run_started_at: str | None
    last_run_finished_at: str | None
    last_model_calls: int
    last_generic_title_model_calls: int
    last_generic_interpretation_model_calls: int
    last_generic_brief_model_calls: int
    last_buy_points_selected: int
    last_buy_points_succeeded: int
    last_buy_points_failed: int
    last_buy_points_reused: int
    last_buy_points_latest_offer_count: int
    last_buy_points_diagnostics: tuple[str, ...]
    last_statusmatch_project_model_calls: int
    last_statusmatch_projects_succeeded: int
    last_statusmatch_project_outputs: tuple[dict[str, Any], ...]
    last_statusmatch_article_model_calls: int
    last_statusmatch_articles_succeeded: int
    last_statusmatch_article_outputs: tuple[dict[str, Any], ...]
    last_generic_status_opportunities: int
    last_generic_briefs: int
    last_generic_status_article_outputs: tuple[dict[str, Any], ...]
    backlog_count: int
    failed_job_count: int
    historical_failed_job_count: int
    needs_review_count: int
    needs_review_outputs: tuple[dict[str, Any], ...]
    sources: tuple[SourceStatusSummary, ...]


class ModelCallBudgetExceeded(RuntimeError):
    pass


class BudgetedAIProvider:
    def __init__(self, provider: AIProvider, limit: int) -> None:
        if limit < 1:
            raise ValueError("model call limit must be positive")
        self._provider = provider
        self._limit = limit
        self.calls = 0
        self.metadata = provider.metadata

    def generate_structured(self, **kwargs):
        if self.calls >= self._limit:
            raise ModelCallBudgetExceeded(
                f"daily model call limit {self._limit} was reached"
            )
        self.calls += 1
        return self._provider.generate_structured(**kwargs)


def run_daily_cycle(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    adapter_factory: Callable[[str], SourceAdapter],
    *,
    limits: AutomationLimits | None = None,
    now: datetime | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    lease_duration: timedelta = timedelta(hours=1),
    owner_id: str | None = None,
    statusmatch_fetcher: Fetcher | None = None,
    generic_pipeline_mode: str = "v2",
    generic_title_drop_enabled: bool = True,
    knowledge_publish_enabled: bool = False,
    agent_experience_researcher: ExperienceResearcher | None = None,
    agent_interaction_ttl: timedelta = timedelta(hours=24),
    agent_max_model_calls: int = 3,
) -> DailyCycleSummary:
    if generic_pipeline_mode not in {"v1", "v2"}:
        raise ValueError("generic_pipeline_mode must be v1 or v2")
    resolved_limits = limits or AutomationLimits()
    current = _as_utc(now or datetime.now(UTC))
    day_bucket = current.astimezone(BEIJING_TZ).date()
    owner = owner_id or uuid4().hex
    if not acquire_automation_lease(
        session_factory,
        owner_id=owner,
        now=current,
        lease_duration=lease_duration,
    ):
        return _skipped_summary(day_bucket, "active database lease")

    run_id: str | None = None
    source_summaries: list[SourceCycleSummary] = []
    processing_payload: dict[str, Any] = {}
    lifecycle_payload: dict[str, int] = {"scanned": 0, "updated": 0, "expired": 0}
    monitoring = StatusMatchMonitoringSummary()
    project_processing = StatusMatchProjectProcessingSummary()
    article_discovery = ArticleRouteDiscoverySummary()
    article_preparation = ArticleProjectPreparationSummary()
    article_processing = StatusMatchArticleProcessingSummary()
    buy_points_processing = BuyPointsProcessingSummary(
        selected=0,
        attempted=0,
        succeeded=0,
        failed=0,
        reused=0,
        latest_offer_count=0,
        diagnostics=(),
        documents=(),
    )
    budgeted = BudgetedAIProvider(provider, resolved_limits.model_calls)
    backlog = 0
    needs_review = 0
    waiting = WaitCheckSummary(status=WaitCheckStatus.NO_GOAL)
    global_error: str | None = None
    try:
        with session_factory.begin() as session:
            seed_sources(session)
            selected_source_ids = _selected_source_ids(session, source_ids)
            run = _start_run(
                session,
                day_bucket=day_bucket,
                owner_id=owner,
                limits=resolved_limits,
                now=current,
            )
            run_id = str(run.id)

        try:
            from journeyplus.statusmatch.monitoring import monitor_statusmatch_projects
            monitoring = monitor_statusmatch_projects(
                session_factory, statusmatch_fetcher or HttpxFetcher(), checked_at=current
            )
        except Exception as exc:
            monitoring = StatusMatchMonitoringSummary(
                errors=(_safe_error(exc),)
            )

        for source_id in selected_source_ids:
            summary = _run_source_collection(
                session_factory,
                source_id=source_id,
                day_bucket=day_bucket,
                adapter_factory=adapter_factory,
                max_items=resolved_limits.source_items_per_source,
                now=current,
            )
            source_summaries.append(summary)

        if BUY_POINTS_SOURCE_ID in selected_source_ids:
            buy_points_processing = process_pending_buy_points(
                session_factory,
                limit=resolved_limits.documents,
            )

        try:
            with session_factory.begin() as session:
                article_discovery = discover_statusmatch_article_routes(
                    session,
                    source_ids=list(selected_source_ids),
                )
            from journeyplus.statusmatch.articles import prepare_article_projects_in_phases
            article_preparation = prepare_article_projects_in_phases(
                session_factory, statusmatch_fetcher or HttpxFetcher(),
                hosts=list(article_discovery.project_hosts), checked_at=current
            )
        except Exception as exc:
            global_error = _safe_error(exc)

        try:
            project_processing = process_pending_statusmatch_projects(
                session_factory,
                budgeted,
                limit=resolved_limits.documents,
            )
        except Exception as exc:
            project_processing = StatusMatchProjectProcessingSummary(
                selected=1,
                attempted=1,
                failed=1,
                errors=(_safe_error(exc),),
            )

        remaining_after_projects = max(
            resolved_limits.documents - project_processing.attempted,
            0,
        )
        if remaining_after_projects:
            try:
                article_processing = process_pending_statusmatch_articles(
                    session_factory,
                    budgeted,
                    limit=remaining_after_projects,
                )
            except Exception as exc:
                article_processing = StatusMatchArticleProcessingSummary(
                    selected=1,
                    attempted=1,
                    failed=1,
                    errors=(_safe_error(exc),),
                )

        generic_limit = max(
            remaining_after_projects - article_processing.attempted,
            0,
        )
        try:
            if (
                generic_limit
                and GENERIC_PUBLIC_SOURCE_ID in selected_source_ids
                and generic_pipeline_mode == "v2"
            ):
                processing = process_pending_articles(
                    session_factory,
                    budgeted,
                    limit=generic_limit,
                    title_drop_enabled=generic_title_drop_enabled,
                )
                generic_payload = asdict(processing)
            elif generic_limit:
                legacy_source_ids = [
                    source_id
                    for source_id in selected_source_ids
                    if source_id
                    not in {"status_services_mail", BUY_POINTS_SOURCE_ID}
                ]
                if legacy_source_ids:
                    processing = process_pending_documents(
                        session_factory,
                        budgeted,
                        source_ids=legacy_source_ids,
                        limit=generic_limit,
                    )
                    legacy_payload = asdict(processing)
                    generic_payload = {
                        **legacy_payload,
                        "title_dropped": 0,
                        "body_processed": legacy_payload["attempted"],
                        "opportunities": legacy_payload["events"],
                        "model_calls": 0,
                        "title_model_calls": 0,
                        "interpretation_model_calls": 0,
                        "brief_model_calls": 0,
                    }
                else:
                    generic_payload = {
                        "selected": 0,
                        "attempted": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "stopped_early": False,
                        "status_opportunities": 0,
                        "title_dropped": 0,
                        "body_processed": 0,
                        "opportunities": 0,
                        "briefs": 0,
                        "model_calls": 0,
                        "title_model_calls": 0,
                        "interpretation_model_calls": 0,
                        "brief_model_calls": 0,
                        "documents": (),
                    }
            else:
                generic_payload = {
                    "selected": 0,
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "stopped_early": False,
                    "status_opportunities": 0,
                    "title_dropped": 0,
                    "body_processed": 0,
                    "opportunities": 0,
                    "briefs": 0,
                    "model_calls": 0,
                    "title_model_calls": 0,
                    "interpretation_model_calls": 0,
                    "brief_model_calls": 0,
                    "documents": (),
                }
            processing_payload = {
                "selected": generic_payload["selected"],
                "attempted": generic_payload["attempted"],
                "succeeded": generic_payload["succeeded"],
                "failed": generic_payload["failed"],
                "stopped_early": generic_payload["stopped_early"],
                "status_opportunities": generic_payload["status_opportunities"],
                "opportunities": generic_payload["opportunities"],
                "briefs": generic_payload["briefs"],
                "generic_model_calls": {
                    "title_batches": generic_payload["title_model_calls"],
                    "article_interpretation": generic_payload[
                        "interpretation_model_calls"
                    ],
                    "article_briefs": generic_payload["brief_model_calls"],
                },
                "statusmatch_monitoring": asdict(monitoring),
                "statusmatch_article_discovery": asdict(article_discovery),
                "statusmatch_article_preparation": asdict(article_preparation),
                "statusmatch_project_processing": asdict(project_processing),
                "statusmatch_article_processing": asdict(article_processing),
                "buy_points_processing": asdict(buy_points_processing),
                "generic_documents": generic_payload,
            }
            if knowledge_publish_enabled:
                from journeyplus.knowledge.refresh import KnowledgeRefreshService
                processing_payload['knowledge_outputs']=KnowledgeRefreshService(session_factory,budgeted).pending(limit=resolved_limits.documents)
        except Exception as exc:
            global_error = _safe_error(exc)
            processing_payload = {
                "selected": 0,
                "succeeded": 0,
                "failed": 1,
                "error": global_error,
                "statusmatch_monitoring": asdict(monitoring),
                "statusmatch_article_discovery": asdict(article_discovery),
                "statusmatch_article_preparation": asdict(article_preparation),
                "statusmatch_project_processing": asdict(project_processing),
                "statusmatch_article_processing": asdict(article_processing),
                "buy_points_processing": asdict(buy_points_processing),
            }

        # V2 waiting owns a short transaction and never invokes a model. Keep its
        # query schema away from the legacy controller during staged rollout.
        from journeyplus.agent.workspace import WorkspaceWaitService,WorkspaceService
        try:
            removed=WorkspaceService(session_factory,None).cleanup(at=current)
            processing_payload['workspace_cleanup']={'status':'COMPLETED','removed_workspaces':removed}
        except Exception as exc:
            processing_payload['workspace_cleanup']={'status':'FAILED','error_type':type(exc).__name__}
        try:
            paused=session_factory.kw.get('info',{}).get('user_business_writes_paused',False)
            workspace_waiting = {'status':'PAUSED','model_calls':0} if paused else WorkspaceWaitService(session_factory).check()
        except Exception as exc:
            workspace_waiting = {"status": "FAILED", "model_calls": 0, "error_type": type(exc).__name__}
        processing_payload["workspace_waiting"] = workspace_waiting

        with session_factory.begin() as session:
            lifecycle = advance_lifecycles(session, now=current)
            article_lifecycle = advance_article_lifecycles(session, now=current)
            lifecycle_payload = {
                "scanned": lifecycle.scanned + article_lifecycle.scanned,
                "updated": lifecycle.updated + article_lifecycle.updated,
                "expired": lifecycle.expired + article_lifecycle.expired,
                "status_events": asdict(lifecycle),
                "article_opportunities": asdict(article_lifecycle),
            }
            waiting = WaitCheckSummary(status='PAUSED',agent_called=False) if session.info.get('user_business_writes_paused') else WaitGoalService(session).check_current(
                lambda goal, result: AgentController(
                    session,
                    budgeted,
                    interaction_ttl=agent_interaction_ttl,
                    max_model_calls=agent_max_model_calls,
                    experience_researcher=agent_experience_researcher,
                    degrade_provider_errors=False,
                ).resume_wait_goal(goal, result)
            )
            if workspace_waiting['status']!='NO_ACTIVE_GOAL':
                waiting=WaitCheckSummary(status=workspace_waiting['status'],goal_id=workspace_waiting.get('goal_id'),
                    matching_count=workspace_waiting.get('matching_count',0),agent_called=False,
                    error=workspace_waiting.get('error_type'))
            processing_payload["agent_waiting"] = waiting.model_dump(mode="json")
            processing_payload["expired_agent_interactions_deleted"] = (
                cleanup_expired_interactions(session, now=current)
            )
            backlog = (
                pending_article_count(
                    session,
                    budgeted,
                    title_drop_enabled=generic_title_drop_enabled,
                )
                if generic_pipeline_mode == "v2"
                else 0
            )
            legacy_source_ids = [
                source_id
                for source_id in selected_source_ids
                if source_id != "status_services_mail"
                and source_id != BUY_POINTS_SOURCE_ID
                and (
                    source_id != GENERIC_PUBLIC_SOURCE_ID
                    or generic_pipeline_mode == "v1"
                )
            ]
            if legacy_source_ids:
                backlog += pending_document_count(
                    session, budgeted, source_ids=legacy_source_ids
                )
            backlog += pending_buy_points_count(session)
            backlog += pending_statusmatch_article_count(session, budgeted)
            needs_review = int(
                session.scalar(
                    select(func.count())
                    .select_from(StatusEvent)
                    .where(StatusEvent.status == "NEEDS_REVIEW")
                )
                or 0
            )
            needs_review += _current_article_needs_review_count(session)
            _refresh_pending_states(
                session,
                budgeted,
                generic_title_drop_enabled=generic_title_drop_enabled,
            )
            run = session.get(AutomationRun, run.id)
            assert run is not None
            source_failures = sum(
                item.status == RunStatus.FAILED for item in source_summaries
            )
            processing_failures = int(processing_payload.get("failed", 0))
            knowledge_failures = any(r.get("status")=="FAILED" or r.get("briefs",{}).get("status")=="FAILED" for r in processing_payload.get("knowledge_outputs",[]))
            project_failures = project_processing.failed
            article_failures = article_processing.failed
            buy_points_failures = buy_points_processing.failed
            run.status = (
                RunStatus.SUCCEEDED
                if not source_failures
                and not processing_failures
                and not knowledge_failures
                and not project_failures
                and not article_failures
                and not buy_points_failures
                and not global_error
                and not monitoring.errors
                and not article_preparation.monitoring.errors
                else RunStatus.FAILED
            )
            run.source_results = [asdict(item) for item in source_summaries]
            run.processing_result = processing_payload
            run.lifecycle_result = lifecycle_payload
            run.model_calls = budgeted.calls
            run.backlog_count = backlog
            run.needs_review_count = needs_review
            run.error = global_error
            run.finished_at = _completion_time(current)
            final_status = run.status
    except Exception as exc:
        global_error = _safe_error(exc)
        final_status = RunStatus.FAILED
        if run_id is not None:
            with session_factory.begin() as session:
                run = session.get(AutomationRun, UUID(run_id))
                if run is not None:
                    run.status = RunStatus.FAILED
                    run.error = global_error
                    run.finished_at = _completion_time(current)
    finally:
        release_automation_lease(session_factory, owner_id=owner, now=current)

    generic_model_calls = processing_payload.get("generic_model_calls", {})
    return DailyCycleSummary(
        run_id=run_id,
        day_bucket=day_bucket.isoformat(),
        status=str(final_status),
        skipped=False,
        skip_reason=None,
        error=global_error,
        sources=tuple(source_summaries),
        documents_selected=int(processing_payload.get("selected", 0)),
        documents_succeeded=int(processing_payload.get("succeeded", 0)),
        documents_failed=int(processing_payload.get("failed", 0)),
        model_calls=budgeted.calls,
        generic_title_model_calls=int(generic_model_calls.get("title_batches", 0)),
        generic_interpretation_model_calls=int(
            generic_model_calls.get("article_interpretation", 0)
        ),
        generic_brief_model_calls=int(
            generic_model_calls.get("article_briefs", 0)
        ),
        buy_points_selected=buy_points_processing.selected,
        buy_points_succeeded=buy_points_processing.succeeded,
        buy_points_failed=buy_points_processing.failed,
        buy_points_reused=buy_points_processing.reused,
        buy_points_latest_offer_count=buy_points_processing.latest_offer_count,
        buy_points_diagnostics=buy_points_processing.diagnostics,
        lifecycle_scanned=lifecycle_payload["scanned"],
        lifecycle_updated=lifecycle_payload["updated"],
        lifecycle_expired=lifecycle_payload["expired"],
        statusmatch_projects_checked=monitoring.projects_checked,
        statusmatch_pages_checked=monitoring.pages_checked,
        statusmatch_pages_changed=monitoring.pages_changed,
        statusmatch_projects_archived=monitoring.projects_archived,
        statusmatch_errors=monitoring.errors,
        statusmatch_projects_selected=project_processing.selected,
        statusmatch_projects_succeeded=project_processing.succeeded,
        statusmatch_projects_failed=project_processing.failed,
        statusmatch_project_model_calls=project_processing.model_calls,
        statusmatch_project_errors=project_processing.errors,
        statusmatch_project_outputs=tuple(
            asdict(item) for item in project_processing.projects
        ),
        statusmatch_article_routes_created=article_discovery.routes_created,
        statusmatch_article_hosts_fetched=article_preparation.hosts_fetched,
        statusmatch_articles_selected=article_processing.selected,
        statusmatch_articles_succeeded=article_processing.succeeded,
        statusmatch_articles_failed=article_processing.failed,
        statusmatch_article_model_calls=article_processing.model_calls,
        statusmatch_article_errors=(
            *article_preparation.monitoring.errors,
            *article_processing.errors,
        ),
        statusmatch_article_outputs=tuple(
            asdict(item) for item in article_processing.routes
        ),
        agent_wait_status=waiting.status,
        agent_wait_matching_count=waiting.matching_count,
        agent_wait_model_called=waiting.agent_called,
        agent_wait_error=waiting.error,
        backlog_count=backlog,
        needs_review_count=needs_review,
        knowledge_outputs=tuple(processing_payload.get("knowledge_outputs", [])),
    )


def automation_status(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    generic_title_drop_enabled: bool = True,
) -> AutomationStatusSummary:
    with session_factory.begin() as session:
        sources = seed_sources(session)
        _ensure_source_states(session, [source.id for source in sources])
        _refresh_pending_states(
            session,
            provider,
            generic_title_drop_enabled=generic_title_drop_enabled,
        )
        lease = session.get(AutomationLease, LEASE_NAME)
        last_run = session.scalar(
            select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(1)
        )
        states = {
            state.source_id: state
            for state in session.scalars(select(SourceAutomationState))
        }
        backlog = pending_article_count(
            session,
            provider,
            title_drop_enabled=generic_title_drop_enabled,
        )
        backlog += pending_statusmatch_article_count(session, provider)
        backlog += pending_buy_points_count(session)
        historical_failed_jobs = int(
            session.scalar(
                select(func.count())
                .select_from(JobRun)
                .where(JobRun.status == RunStatus.FAILED)
            )
            or 0
        )
        needs_review = int(
            session.scalar(
                select(func.count())
                .select_from(StatusEvent)
                .where(StatusEvent.status == "NEEDS_REVIEW")
            )
            or 0
        )
        needs_review += _current_article_needs_review_count(session)
        source_results = tuple(
            _source_status(source, states[source.id]) for source in sources
        )
        processing = last_run.processing_result if last_run else {}
        generic_calls = processing.get("generic_model_calls", {})
        statusmatch_projects = processing.get(
            "statusmatch_project_processing", {}
        )
        statusmatch_articles = processing.get(
            "statusmatch_article_processing", {}
        )
        buy_points = processing.get("buy_points_processing", {})
        generic_documents = processing.get("generic_documents", {})
        statusmatch_article_outputs = _article_outputs_with_links(
            session,
            statusmatch_articles.get("routes", ()),
        )
        generic_status_article_outputs = _article_outputs_with_links(
            session,
            (
                item
                for item in generic_documents.get("documents", ())
                if item.get("document_label")
                == DocumentLabel.STATUS_OPPORTUNITY
            ),
        )
        return AutomationStatusSummary(
            lease_owner=lease.owner_id if lease else None,
            lease_expires_at=_iso(lease.expires_at) if lease else None,
            last_run_id=str(last_run.id) if last_run else None,
            last_run_day=last_run.day_bucket.isoformat() if last_run else None,
            last_run_status=last_run.status if last_run else None,
            last_run_started_at=(
                _iso(last_run.started_at) if last_run else None
            ),
            last_run_finished_at=(
                _iso(_effective_run_finished_at(last_run)) if last_run else None
            ),
            last_model_calls=last_run.model_calls if last_run else 0,
            last_generic_title_model_calls=int(
                generic_calls.get("title_batches", 0)
            ),
            last_generic_interpretation_model_calls=int(
                generic_calls.get("article_interpretation", 0)
            ),
            last_generic_brief_model_calls=int(
                generic_calls.get("article_briefs", 0)
            ),
            last_buy_points_selected=int(buy_points.get("selected", 0)),
            last_buy_points_succeeded=int(buy_points.get("succeeded", 0)),
            last_buy_points_failed=int(buy_points.get("failed", 0)),
            last_buy_points_reused=int(buy_points.get("reused", 0)),
            last_buy_points_latest_offer_count=int(
                buy_points.get("latest_offer_count", 0)
            ),
            last_buy_points_diagnostics=tuple(
                buy_points.get("diagnostics", ())
            ),
            last_statusmatch_project_model_calls=int(
                statusmatch_projects.get("model_calls", 0)
            ),
            last_statusmatch_projects_succeeded=int(
                statusmatch_projects.get("succeeded", 0)
            ),
            last_statusmatch_project_outputs=tuple(
                statusmatch_projects.get("projects", ())
            ),
            last_statusmatch_article_model_calls=int(
                statusmatch_articles.get("model_calls", 0)
            ),
            last_statusmatch_articles_succeeded=int(
                statusmatch_articles.get("succeeded", 0)
            ),
            last_statusmatch_article_outputs=statusmatch_article_outputs,
            last_generic_status_opportunities=int(
                generic_documents.get(
                    "status_opportunities",
                    processing.get("status_opportunities", 0),
                )
            ),
            last_generic_briefs=int(
                generic_documents.get("briefs", processing.get("briefs", 0))
            ),
            last_generic_status_article_outputs=(
                generic_status_article_outputs
            ),
            backlog_count=backlog,
            failed_job_count=_last_run_failure_count(last_run),
            historical_failed_job_count=historical_failed_jobs,
            needs_review_count=needs_review,
            needs_review_outputs=_needs_review_outputs(session),
            sources=source_results,
        )


def acquire_automation_lease(
    session_factory: sessionmaker[Session],
    *,
    owner_id: str,
    now: datetime,
    lease_duration: timedelta,
) -> bool:
    if lease_duration <= timedelta(0):
        raise ValueError("lease duration must be positive")
    current = _as_utc(now)
    for _attempt in range(3):
        try:
            with session_factory.begin() as session:
                lease = session.scalar(
                    select(AutomationLease)
                    .where(AutomationLease.name == LEASE_NAME)
                    .with_for_update()
                )
                if lease is None:
                    session.add(
                        AutomationLease(
                            name=LEASE_NAME,
                            owner_id=owner_id,
                            acquired_at=current,
                            expires_at=current + lease_duration,
                        )
                    )
                    session.flush()
                    return True
                if (
                    lease.owner_id is not None
                    and lease.owner_id != owner_id
                    and lease.expires_at is not None
                    and _as_utc(lease.expires_at) > current
                ):
                    return False
                lease.owner_id = owner_id
                lease.acquired_at = current
                lease.expires_at = current + lease_duration
                return True
        except IntegrityError:
            continue
    return False


def release_automation_lease(
    session_factory: sessionmaker[Session],
    *,
    owner_id: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        lease = session.scalar(
            select(AutomationLease)
            .where(AutomationLease.name == LEASE_NAME)
            .with_for_update()
        )
        if lease is not None and lease.owner_id == owner_id:
            lease.owner_id = None
            lease.expires_at = _as_utc(now)


def _run_source_collection(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    adapter_factory: Callable[[str], SourceAdapter],
    max_items: int,
    now: datetime,
) -> SourceCycleSummary:
    key = f"daily:{day_bucket.isoformat()}:{source_id}"
    try:
        from journeyplus.sources.collection import collect_in_phases
        collection = collect_in_phases(
            session_factory, adapter_factory(source_id), idempotency_key=key, max_items=max_items
        )
        _record_source_success(
            session_factory,
            source_id=source_id,
            day_bucket=day_bucket,
            new_documents=collection.new_versions,
            now=now,
        )
        return SourceCycleSummary(
            source_id=source_id,
            status=RunStatus.SUCCEEDED,
            discovered=collection.discovered,
            considered=collection.considered,
            new_documents=collection.new_versions,
            reused=collection.reused_run,
        )
    except Exception as exc:
        error = _safe_error(exc)
        _record_collection_failure(
            session_factory,
            source_id=source_id,
            idempotency_key=key,
            error=error,
            now=now,
        )
        _record_source_failure(
            session_factory,
            source_id=source_id,
            day_bucket=day_bucket,
            error=error,
            now=now,
        )
        return SourceCycleSummary(
            source_id=source_id,
            status=RunStatus.FAILED,
            error=error,
        )


def _record_collection_failure(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    idempotency_key: str,
    error: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        run = session.scalar(
            select(CollectionRun).where(
                CollectionRun.idempotency_key == idempotency_key
            )
        )
        if run is None:
            run = CollectionRun(
                source_id=source_id,
                idempotency_key=idempotency_key,
                status=RunStatus.FAILED,
            )
            session.add(run)
        run.status = RunStatus.FAILED
        run.error = error
        run.started_at = run.started_at or now
        run.finished_at = now


def _record_source_success(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    new_documents: int,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        state = _source_state(session, source_id)
        state.last_day_bucket = day_bucket
        state.last_attempt_at = now
        state.last_success_at = now
        state.last_error = None
        state.consecutive_failures = 0
        state.last_new_document_count = new_documents


def _record_source_failure(
    session_factory: sessionmaker[Session],
    *,
    source_id: str,
    day_bucket: date,
    error: str,
    now: datetime,
) -> None:
    with session_factory.begin() as session:
        state = _source_state(session, source_id)
        state.last_day_bucket = day_bucket
        state.last_attempt_at = now
        state.last_failure_at = now
        state.last_error = error
        state.consecutive_failures += 1
        state.last_new_document_count = 0


def _refresh_pending_states(
    session: Session,
    provider: AIProvider,
    *,
    generic_title_drop_enabled: bool,
) -> None:
    source_ids = [item.source_id for item in SOURCE_REGISTRY]
    _ensure_source_states(session, source_ids)
    for source_id in source_ids:
        state = session.get(SourceAutomationState, source_id)
        assert state is not None
        state.pending_document_count = (
            pending_article_count(
                session,
                provider,
                title_drop_enabled=generic_title_drop_enabled,
            )
            if source_id == GENERIC_PUBLIC_SOURCE_ID
            else pending_buy_points_count(session)
            if source_id == BUY_POINTS_SOURCE_ID
            else 0
        )


def _current_article_needs_review_count(session: Session) -> int:
    ranked_documents = (
        select(
            DocumentVersion.id.label("document_id"),
            DocumentVersion.source_item_id.label("source_item_id"),
            func.row_number()
            .over(
                partition_by=DocumentVersion.source_item_id,
                order_by=(
                    DocumentVersion.created_at.desc(),
                    DocumentVersion.id.desc(),
                ),
            )
            .label("document_rank"),
        )
        .subquery()
    )
    ranked_analyses = (
        select(
            ArticleAnalysisRecord.document_version_id.label("document_id"),
            ArticleAnalysisRecord.status.label("status"),
            func.row_number()
            .over(
                partition_by=ArticleAnalysisRecord.document_version_id,
                order_by=(
                    ArticleAnalysisRecord.created_at.desc(),
                    ArticleAnalysisRecord.id.desc(),
                ),
            )
            .label("analysis_rank"),
        )
        .subquery()
    )
    return int(
        session.scalar(
            select(func.count())
            .select_from(ranked_documents)
            .join(
                ranked_analyses,
                ranked_analyses.c.document_id
                == ranked_documents.c.document_id,
            )
            .where(
                ranked_documents.c.document_rank == 1,
                ranked_analyses.c.analysis_rank == 1,
                ranked_analyses.c.status == "NEEDS_REVIEW",
            )
        )
        or 0
    )


def _article_outputs_with_links(
    session: Session,
    outputs: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    enriched: list[dict[str, Any]] = []
    for output in outputs:
        payload = dict(output)
        document_id = payload.get("document_version_id")
        try:
            document = (
                session.get(DocumentVersion, UUID(str(document_id)))
                if document_id
                else None
            )
        except ValueError:
            document = None
        item = (
            session.get(SourceItem, document.source_item_id)
            if document is not None
            else None
        )
        if item is not None:
            payload["article_title"] = item.title
            payload["article_url"] = item.canonical_url
        enriched.append(payload)
    return tuple(enriched)


def _needs_review_outputs(session: Session) -> tuple[dict[str, Any], ...]:
    outputs: list[dict[str, Any]] = []
    events = session.scalars(
        select(StatusEvent)
        .where(StatusEvent.status == "NEEDS_REVIEW")
        .order_by(StatusEvent.updated_at.asc())
    )
    for event in events:
        fact_set = (
            session.get(FactSetRecord, event.current_fact_set_id)
            if event.current_fact_set_id is not None
            else None
        )
        outputs.append(
            {
                "kind": "official_source_conflict",
                "program": event.program,
                "conflicts": _fact_conflicts(fact_set.facts if fact_set else {}),
            }
        )

    ranked_documents = (
        select(
            DocumentVersion.id.label("document_id"),
            DocumentVersion.source_item_id.label("source_item_id"),
            func.row_number()
            .over(
                partition_by=DocumentVersion.source_item_id,
                order_by=(
                    DocumentVersion.created_at.desc(),
                    DocumentVersion.id.desc(),
                ),
            )
            .label("document_rank"),
        )
        .subquery()
    )
    ranked_analyses = (
        select(
            ArticleAnalysisRecord.source_item_id.label("source_item_id"),
            ArticleAnalysisRecord.document_version_id.label("document_id"),
            ArticleAnalysisRecord.label.label("label"),
            ArticleAnalysisRecord.confidence.label("confidence"),
            ArticleAnalysisRecord.reason.label("reason"),
            ArticleAnalysisRecord.status.label("status"),
            ArticleAnalysisRecord.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=ArticleAnalysisRecord.document_version_id,
                order_by=(
                    ArticleAnalysisRecord.created_at.desc(),
                    ArticleAnalysisRecord.id.desc(),
                ),
            )
            .label("analysis_rank"),
        )
        .subquery()
    )
    rows = session.execute(
        select(ranked_analyses, SourceItem)
        .join(
            ranked_documents,
            ranked_documents.c.document_id == ranked_analyses.c.document_id,
        )
        .join(SourceItem, SourceItem.id == ranked_analyses.c.source_item_id)
        .where(
            ranked_documents.c.document_rank == 1,
            ranked_analyses.c.analysis_rank == 1,
            ranked_analyses.c.status == "NEEDS_REVIEW",
        )
        .order_by(ranked_analyses.c.created_at.asc())
    )
    for row in rows:
        item = row.SourceItem
        outputs.append(
            {
                "kind": "article_classification_review",
                "article_title": item.title,
                "article_url": item.canonical_url,
                "label": row.label,
                "confidence": row.confidence,
                "reason": row.reason,
            }
        )
    return tuple(outputs)


def _fact_conflicts(
    value: Any,
    *,
    path: str = "",
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("conflict") is True:
            detail = {
                key: value[key]
                for key in (
                    "value",
                    "alternatives",
                    "conflict_note",
                    "region",
                    "scope",
                    "eligibility",
                    "cost",
                )
                if value.get(key) not in (None, [], "")
            }
            conflicts.append({"field": path or "facts", **detail})
        for key, nested in value.items():
            if key == "evidence":
                continue
            nested_path = f"{path}.{key}" if path else key
            conflicts.extend(_fact_conflicts(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            conflicts.extend(_fact_conflicts(nested, path=f"{path}[{index}]"))
    return conflicts


def _last_run_failure_count(last_run: AutomationRun | None) -> int:
    if last_run is None:
        return 0
    processing = last_run.processing_result or {}
    source_failures = sum(
        item.get("status") == RunStatus.FAILED
        for item in (last_run.source_results or ())
    )
    return source_failures + sum(
        int(payload.get("failed", 0))
        for payload in (
            processing,
            processing.get("statusmatch_project_processing", {}),
            processing.get("statusmatch_article_processing", {}),
            processing.get("buy_points_processing", {}),
        )
    )


def _completion_time(started_at: datetime) -> datetime:
    return max(
        datetime.now(UTC),
        _as_utc(started_at) + timedelta(microseconds=1),
    )


def _effective_run_finished_at(run: AutomationRun) -> datetime | None:
    if run.finished_at is None:
        return None
    if (
        run.started_at is not None
        and _as_utc(run.finished_at) <= _as_utc(run.started_at)
        and run.updated_at is not None
    ):
        return run.updated_at
    return run.finished_at


def _source_state(session: Session, source_id: str) -> SourceAutomationState:
    state = session.get(SourceAutomationState, source_id)
    if state is None:
        state = SourceAutomationState(source_id=source_id)
        session.add(state)
        session.flush()
    return state


def _ensure_source_states(session: Session, source_ids: list[str]) -> None:
    for source_id in source_ids:
        _source_state(session, source_id)


def _selected_source_ids(
    session: Session,
    source_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if source_ids is None:
        return automatically_scheduled_source_ids(session)
    known = {item.source_id for item in SOURCE_REGISTRY}
    unknown = set(source_ids) - known
    if unknown:
        raise ValueError(f"Unknown automation sources: {sorted(unknown)}")
    return list(dict.fromkeys(source_ids))


def _start_run(
    session: Session,
    *,
    day_bucket: date,
    owner_id: str,
    limits: AutomationLimits,
    now: datetime,
) -> AutomationRun:
    key = f"daily:{day_bucket.isoformat()}"
    run = session.scalar(
        select(AutomationRun).where(AutomationRun.idempotency_key == key)
    )
    if run is None:
        run = AutomationRun(
            idempotency_key=key,
            day_bucket=day_bucket,
            status=RunStatus.PENDING,
            owner_id=owner_id,
        )
        session.add(run)
    run.status = RunStatus.RUNNING
    run.attempts = (run.attempts or 0) + 1
    run.owner_id = owner_id
    run.limits = asdict(limits)
    run.error = None
    run.started_at = now
    run.finished_at = None
    session.flush()
    return run


def _source_status(
    source: Source,
    state: SourceAutomationState,
) -> SourceStatusSummary:
    return SourceStatusSummary(
        source_id=source.id,
        enabled=source.enabled,
        automatic_scheduling=source.automatic_scheduling,
        collection_cadence=source.collection_cadence,
        last_day_bucket=(
            state.last_day_bucket.isoformat() if state.last_day_bucket else None
        ),
        last_attempt_at=_iso(state.last_attempt_at),
        last_success_at=_iso(state.last_success_at),
        last_failure_at=_iso(state.last_failure_at),
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
        last_new_document_count=state.last_new_document_count,
        pending_document_count=state.pending_document_count,
    )


def _skipped_summary(day_bucket: date, reason: str) -> DailyCycleSummary:
    return DailyCycleSummary(
        run_id=None,
        day_bucket=day_bucket.isoformat(),
        status=RunStatus.SKIPPED,
        skipped=True,
        skip_reason=reason,
        error=None,
        sources=(),
        documents_selected=0,
        documents_succeeded=0,
        documents_failed=0,
        model_calls=0,
        generic_title_model_calls=0,
        generic_interpretation_model_calls=0,
        generic_brief_model_calls=0,
        buy_points_selected=0,
        buy_points_succeeded=0,
        buy_points_failed=0,
        buy_points_reused=0,
        buy_points_latest_offer_count=0,
        buy_points_diagnostics=(),
        lifecycle_scanned=0,
        lifecycle_updated=0,
        lifecycle_expired=0,
        statusmatch_projects_checked=0,
        statusmatch_pages_checked=0,
        statusmatch_pages_changed=0,
        statusmatch_projects_archived=0,
        statusmatch_errors=(),
        statusmatch_projects_selected=0,
        statusmatch_projects_succeeded=0,
        statusmatch_projects_failed=0,
        statusmatch_project_model_calls=0,
        statusmatch_project_errors=(),
        statusmatch_project_outputs=(),
        statusmatch_article_routes_created=0,
        statusmatch_article_hosts_fetched=(),
        statusmatch_articles_selected=0,
        statusmatch_articles_succeeded=0,
        statusmatch_articles_failed=0,
        statusmatch_article_model_calls=0,
        statusmatch_article_errors=(),
        statusmatch_article_outputs=(),
        agent_wait_status=WaitCheckStatus.NO_GOAL,
        agent_wait_matching_count=0,
        agent_wait_model_called=False,
        agent_wait_error=None,
        backlog_count=0,
        needs_review_count=0,
    )


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:1000]


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
