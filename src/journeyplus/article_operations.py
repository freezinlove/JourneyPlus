from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.article_pipeline.briefs import (
    ARTICLE_BRIEF_PROMPT_VERSION,
    ARTICLE_BRIEF_SCHEMA_VERSION,
    ArticleBriefGenerator,
)
from journeyplus.article_pipeline.contracts import TitleScreenDecision
from journeyplus.article_pipeline.interpretation import (
    ARTICLE_INTERPRETATION_PROMPT_VERSION,
    ARTICLE_INTERPRETATION_SCHEMA_VERSION,
    ArticleInterpreter,
)
from journeyplus.article_pipeline.screening import (
    TITLE_SCREEN_PROMPT_VERSION,
    TITLE_SCREEN_SCHEMA_VERSION,
    BatchTitleScreener,
)
from journeyplus.article_pipeline.visibility import (
    ArticleArchiveReason,
    ArticleVisibilityPolicy,
)
from journeyplus.contracts import DocumentLabel, RunStatus
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    JobRun,
    ReviewDecision,
    SourceItem,
)
from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing
from journeyplus.statusmatch.articles import is_third_party_statusmatch_article


GENERIC_PUBLIC_SOURCE_ID = "loyaltylobby_feed"


@dataclass(frozen=True, slots=True)
class ArticleDocumentProcessingResult:
    document_version_id: str
    source_id: str
    article_title: str
    article_url: str
    title_decision: str
    document_label: str | None
    opportunity_ids: tuple[str, ...] = ()
    brief_ids: tuple[str, ...] = ()
    reused_title_screen: bool = False
    reused_interpretation: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ArticleProcessingSummary:
    selected: int
    attempted: int
    succeeded: int
    failed: int
    title_dropped: int
    body_processed: int
    status_opportunities: int
    opportunities: int
    briefs: int
    model_calls: int
    title_model_calls: int
    interpretation_model_calls: int
    brief_model_calls: int
    documents: tuple[ArticleDocumentProcessingResult, ...]
    stopped_early: bool = False


def article_workflow_idempotency_key(
    document_id: UUID,
    provider: AIProvider,
    *,
    title_drop_enabled: bool = True,
) -> str:
    version_payload = {
        "provider": provider.metadata.config_version,
        "title": [TITLE_SCREEN_PROMPT_VERSION, TITLE_SCREEN_SCHEMA_VERSION],
        "interpretation": [
            ARTICLE_INTERPRETATION_PROMPT_VERSION,
            ARTICLE_INTERPRETATION_SCHEMA_VERSION,
        ],
        "brief": [ARTICLE_BRIEF_PROMPT_VERSION, ARTICLE_BRIEF_SCHEMA_VERSION],
        "title_drop_enabled": title_drop_enabled,
    }
    fingerprint = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True).encode()
    ).hexdigest()[:20]
    return f"article-v2:{document_id}:{fingerprint}"


def pending_article_documents(
    session: Session,
    provider: AIProvider,
    *,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
    limit: int | None = 10,
    title_drop_enabled: bool = True,
) -> list[UUID]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    normalized_ids = (
        [UUID(str(value)) for value in document_ids]
        if document_ids is not None
        else None
    )
    if normalized_ids == []:
        return []
    newer = aliased(DocumentVersion)
    latest_id = (
        select(newer.id)
        .where(newer.source_item_id == DocumentVersion.source_item_id)
        .order_by(newer.created_at.desc(), newer.id.desc())
        .limit(1)
        .correlate(DocumentVersion)
        .scalar_subquery()
    )
    statement = (
        select(DocumentVersion.id)
        .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
        .where(SourceItem.source_id == GENERIC_PUBLIC_SOURCE_ID)
        .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
    )
    if normalized_ids is None:
        statement = statement.where(DocumentVersion.id == latest_id)
    else:
        statement = statement.where(DocumentVersion.id.in_(normalized_ids))
    if published_from is not None:
        statement = statement.where(SourceItem.published_at >= published_from)
    if published_until is not None:
        statement = statement.where(SourceItem.published_at < published_until)
    candidates = [
        document_id
        for document_id in session.scalars(statement)
        if (
            (document := session.get(DocumentVersion, document_id)) is not None
            and not is_third_party_statusmatch_article(session, document)
        )
    ]
    completed = (
        set(
            session.scalars(
                select(JobRun.idempotency_key).where(
                    JobRun.idempotency_key.in_(
                        article_workflow_idempotency_key(
                            item,
                            provider,
                            title_drop_enabled=title_drop_enabled,
                        )
                        for item in candidates
                    ),
                    JobRun.status == "SUCCEEDED",
                )
            )
        )
        if candidates
        else set()
    )
    needs_interpretation_retry = {
        document_id
        for document_id in candidates
        if _document_analysis_needs_review(session, document_id)
    }
    pending = [
        item
        for item in candidates
        if (
            article_workflow_idempotency_key(
                item,
                provider,
                title_drop_enabled=title_drop_enabled,
            )
            not in completed
            or item in needs_interpretation_retry
        )
    ]
    return pending if limit is None else pending[:limit]


def pending_article_count(
    session: Session,
    provider: AIProvider,
    *,
    title_drop_enabled: bool = True,
) -> int:
    return len(
        pending_article_documents(
            session,
            provider,
            limit=None,
            title_drop_enabled=title_drop_enabled,
        )
    )


def process_pending_articles(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
    limit: int = 10,
    stop_on_failure: bool = False,
    title_drop_enabled: bool = True,
) -> ArticleProcessingSummary:
    counted = _CallCountingProvider(provider)
    runtime_provider: AIProvider = counted
    calls_before = _provider_call_count(runtime_provider)
    stage_calls = {"title": 0, "interpretation": 0, "brief": 0}
    with session_factory.begin() as session:
        selected = pending_article_documents(
            session,
            runtime_provider,
            document_ids=document_ids,
            published_from=published_from,
            published_until=published_until,
            limit=limit,
            title_drop_enabled=title_drop_enabled,
        )
        documents = [session.get(DocumentVersion, item) for item in selected]
        if any(document is None for document in documents):
            raise LookupError("A selected article document was not found")
        title_calls_before = _provider_call_count(runtime_provider)
        screenings = BatchTitleScreener(session, runtime_provider).screen(
            [document for document in documents if document is not None]
        )
        stage_calls["title"] += (
            _provider_call_count(runtime_provider) - title_calls_before
        )
        screening_by_id = {
            outcome.result.document_version_id: outcome for outcome in screenings
        }
        article_metadata: dict[UUID, tuple[str, str]] = {}
        for document in documents:
            assert document is not None
            item = session.get(SourceItem, document.source_item_id)
            if item is None:
                raise LookupError("Article source item was not found")
            article_metadata[document.id] = (item.title, item.canonical_url)

    runner = JobRunner(session_factory, max_attempts=1)
    results: list[ArticleDocumentProcessingResult] = []
    stopped_early = False
    for position, document_id in enumerate(selected):
        screening = screening_by_id[document_id]
        article_title, article_url = article_metadata[document_id]
        job_key = article_workflow_idempotency_key(
            document_id,
            runtime_provider,
            title_drop_enabled=title_drop_enabled,
        )
        with session_factory.begin() as session:
            if _document_analysis_needs_review(session, document_id):
                prior_job = session.scalar(
                    select(JobRun).where(JobRun.idempotency_key == job_key)
                )
                if prior_job is not None and prior_job.status == RunStatus.SUCCEEDED:
                    prior_job.status = RunStatus.PENDING
                    prior_job.error = (
                        "Nested article interpretation needs a reliable retry"
                    )
                    prior_job.finished_at = None

        def operation(
            current_document_id: UUID = document_id,
            current_screening=screening,
        ) -> ArticleDocumentProcessingResult:
            effective_decision = current_screening.result.decision
            if (
                effective_decision == TitleScreenDecision.DROP
                and not title_drop_enabled
            ):
                effective_decision = TitleScreenDecision.NEEDS_BODY
            if effective_decision == TitleScreenDecision.DROP:
                return ArticleDocumentProcessingResult(
                    document_version_id=str(current_document_id),
                    source_id=GENERIC_PUBLIC_SOURCE_ID,
                    article_title=article_title,
                    article_url=article_url,
                    title_decision=effective_decision,
                    document_label=None,
                    reused_title_screen=current_screening.reused,
                )
            with session_factory.begin() as session:
                document = session.get(DocumentVersion, current_document_id)
                if document is None:
                    raise LookupError("Article document was not found")
                interpretation_calls_before = _provider_call_count(runtime_provider)
                interpreted = ArticleInterpreter(
                    session, runtime_provider
                ).interpret(document)
                stage_calls["interpretation"] += (
                    _provider_call_count(runtime_provider)
                    - interpretation_calls_before
                )
                document_label = interpreted.interpretation.label
                reused_interpretation = interpreted.reused
                opportunity_ids = tuple(item.id for item in interpreted.opportunities)
                interpretation_error = (
                    (
                        interpreted.run.error
                        or "Article interpretation needs manual review"
                    )
                    if interpreted.run.status == RunStatus.FAILED
                    else None
                )

            if interpretation_error is not None:
                raise ValueError(interpretation_error)

            brief_ids: list[str] = []
            brief_errors: list[str] = []
            for opportunity_id in opportunity_ids:
                brief_session = session_factory()
                brief_calls_before = _provider_call_count(runtime_provider)
                try:
                    opportunity = brief_session.get(
                        ArticleOpportunityRecord, opportunity_id
                    )
                    if opportunity is None:
                        raise LookupError("Article opportunity was not found")
                    generated = ArticleBriefGenerator(
                        brief_session, runtime_provider
                    ).generate(opportunity)
                    opportunity.status = "DRAFT"
                    brief_session.commit()
                    brief_ids.append(str(generated.record.id))
                except Exception as exc:
                    opportunity = brief_session.get(
                        ArticleOpportunityRecord, opportunity_id
                    )
                    if opportunity is not None:
                        opportunity.status = "NEEDS_REVIEW"
                    brief_session.commit()
                    brief_errors.append(f"{type(exc).__name__}: {exc}"[:1000])
                finally:
                    stage_calls["brief"] += (
                        _provider_call_count(runtime_provider) - brief_calls_before
                    )
                    brief_session.close()
            if brief_errors:
                raise ValueError("; ".join(brief_errors))
            return ArticleDocumentProcessingResult(
                document_version_id=str(current_document_id),
                source_id=GENERIC_PUBLIC_SOURCE_ID,
                article_title=article_title,
                article_url=article_url,
                title_decision=effective_decision,
                document_label=document_label,
                opportunity_ids=tuple(str(item) for item in opportunity_ids),
                brief_ids=tuple(brief_ids),
                reused_title_screen=current_screening.reused,
                reused_interpretation=reused_interpretation,
            )

        try:
            result, skipped = runner.execute(
                idempotency_key=job_key,
                job_type="generic_article_v2",
                operation=operation,
                serialize=asdict,
            )
            if not skipped and result is not None:
                results.append(result)
        except Exception as exc:
            with session_factory() as session:
                document_label, opportunity_ids, brief_ids = (
                    _materialized_document_state(session, document_id)
                )
            results.append(
                ArticleDocumentProcessingResult(
                    document_version_id=str(document_id),
                    source_id=GENERIC_PUBLIC_SOURCE_ID,
                    article_title=article_title,
                    article_url=article_url,
                    title_decision=screening.result.decision,
                    document_label=document_label,
                    opportunity_ids=opportunity_ids,
                    brief_ids=brief_ids,
                    reused_title_screen=screening.reused,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            )
            if stop_on_failure:
                stopped_early = position + 1 < len(selected)
                break

    successful = [item for item in results if item.error is None]
    return ArticleProcessingSummary(
        selected=len(selected),
        attempted=len(results),
        succeeded=len(successful),
        failed=sum(item.error is not None for item in results),
        title_dropped=sum(
            item.title_decision == TitleScreenDecision.DROP for item in results
        ),
        body_processed=sum(
            item.title_decision != TitleScreenDecision.DROP for item in results
        ),
        status_opportunities=sum(
            item.document_label == DocumentLabel.STATUS_OPPORTUNITY
            for item in results
        ),
        opportunities=sum(len(item.opportunity_ids) for item in results),
        briefs=sum(len(item.brief_ids) for item in results),
        model_calls=max(_provider_call_count(runtime_provider) - calls_before, 0),
        title_model_calls=stage_calls["title"],
        interpretation_model_calls=stage_calls["interpretation"],
        brief_model_calls=stage_calls["brief"],
        documents=tuple(results),
        stopped_early=stopped_early,
    )


def latest_successful_article_analysis(
    session: Session, source_item_id: UUID
) -> ArticleAnalysisRecord | None:
    return session.scalar(
        select(ArticleAnalysisRecord)
        .where(
            ArticleAnalysisRecord.source_item_id == source_item_id,
            ArticleAnalysisRecord.status == "SUCCEEDED",
        )
        .order_by(ArticleAnalysisRecord.created_at.desc(), ArticleAnalysisRecord.id.desc())
        .limit(1)
    )


def _document_analysis_needs_review(
    session: Session,
    document_id: UUID,
) -> bool:
    status = session.scalar(
        select(ArticleAnalysisRecord.status)
        .where(ArticleAnalysisRecord.document_version_id == document_id)
        .order_by(
            ArticleAnalysisRecord.created_at.desc(),
            ArticleAnalysisRecord.id.desc(),
        )
        .limit(1)
    )
    return status == "NEEDS_REVIEW"


def archive_article_mapping(
    session: Session,
    *,
    opportunity_id: UUID | str,
    reason: str,
    actor: str = "operator",
    now: datetime | None = None,
) -> ArticleOpportunityRecord:
    opportunity = _article_opportunity(session, opportunity_id)
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    before = _visibility_audit_payload(opportunity)
    opportunity.archived_at = current
    opportunity.archive_reason = ArticleArchiveReason.MANUAL
    _record_visibility_decision(
        session,
        opportunity=opportunity,
        action="ARCHIVE_ARTICLE_MAPPING",
        actor=actor,
        reason=reason,
        before=before,
    )
    session.flush()
    return opportunity


def restore_article_mapping(
    session: Session,
    *,
    opportunity_id: UUID | str,
    visibility_until_at: datetime | None = None,
    reason: str,
    actor: str = "operator",
    now: datetime | None = None,
) -> ArticleOpportunityRecord:
    opportunity = _article_opportunity(session, opportunity_id)
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    before = _visibility_audit_payload(opportunity)
    requested_until = (
        as_beijing(visibility_until_at)
        if visibility_until_at is not None
        else as_beijing(opportunity.visibility_until_at)
    )
    if requested_until <= current:
        raise ValueError(
            "Restoring an expired article mapping requires a future visibility time"
        )
    if visibility_until_at is not None:
        opportunity.visibility_until_at = requested_until
        opportunity.visibility_policy = ArticleVisibilityPolicy.MANUAL_OVERRIDE
    opportunity.archived_at = None
    opportunity.archive_reason = None
    _record_visibility_decision(
        session,
        opportunity=opportunity,
        action="RESTORE_ARTICLE_MAPPING",
        actor=actor,
        reason=reason,
        before=before,
    )
    session.flush()
    return opportunity


def extend_article_mapping(
    session: Session,
    *,
    opportunity_id: UUID | str,
    visibility_until_at: datetime,
    reason: str,
    actor: str = "operator",
    now: datetime | None = None,
) -> ArticleOpportunityRecord:
    opportunity = _article_opportunity(session, opportunity_id)
    current = as_beijing(now or datetime.now(BEIJING_TZ))
    requested_until = as_beijing(visibility_until_at)
    if requested_until <= current:
        raise ValueError("Article mapping extension must end in the future")
    before = _visibility_audit_payload(opportunity)
    opportunity.visibility_until_at = requested_until
    opportunity.visibility_policy = ArticleVisibilityPolicy.MANUAL_OVERRIDE
    opportunity.archived_at = None
    opportunity.archive_reason = None
    _record_visibility_decision(
        session,
        opportunity=opportunity,
        action="EXTEND_ARTICLE_MAPPING",
        actor=actor,
        reason=reason,
        before=before,
    )
    session.flush()
    return opportunity


def _article_opportunity(
    session: Session, opportunity_id: UUID | str
) -> ArticleOpportunityRecord:
    opportunity = session.get(ArticleOpportunityRecord, UUID(str(opportunity_id)))
    if opportunity is None:
        raise LookupError("Article opportunity was not found")
    return opportunity


def _visibility_audit_payload(
    opportunity: ArticleOpportunityRecord,
) -> dict[str, str | None]:
    return {
        "visibility_until_at": (
            opportunity.visibility_until_at.isoformat()
            if opportunity.visibility_until_at is not None
            else None
        ),
        "visibility_policy": opportunity.visibility_policy,
        "archived_at": (
            opportunity.archived_at.isoformat()
            if opportunity.archived_at is not None
            else None
        ),
        "archive_reason": opportunity.archive_reason,
    }


def _record_visibility_decision(
    session: Session,
    *,
    opportunity: ArticleOpportunityRecord,
    action: str,
    actor: str,
    reason: str,
    before: dict[str, str | None],
) -> None:
    session.add(
        ReviewDecision(
            action=action,
            entity_type="article_opportunity",
            entity_id=opportunity.id,
            reason=reason,
            actor=actor,
            payload={
                "before": before,
                "after": _visibility_audit_payload(opportunity),
            },
        )
    )


def _materialized_document_state(
    session: Session, document_id: UUID
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    analysis = session.scalar(
        select(ArticleAnalysisRecord)
        .where(ArticleAnalysisRecord.document_version_id == document_id)
        .order_by(
            ArticleAnalysisRecord.created_at.desc(),
            ArticleAnalysisRecord.id.desc(),
        )
        .limit(1)
    )
    if analysis is None:
        return None, (), ()
    opportunities = list(
        session.scalars(
            select(ArticleOpportunityRecord)
            .where(ArticleOpportunityRecord.analysis_id == analysis.id)
            .order_by(ArticleOpportunityRecord.opportunity_index)
        )
    )
    return (
        analysis.label,
        tuple(str(item.id) for item in opportunities),
        tuple(
            str(item.current_brief_id)
            for item in opportunities
            if item.current_brief_id is not None
        ),
    )


def _provider_call_count(provider: AIProvider) -> int:
    value = getattr(provider, "calls", 0)
    return len(value) if isinstance(value, list) else int(value)


class _CallCountingProvider:
    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self.metadata = provider.metadata
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        return self._provider.generate_structured(**kwargs)
