from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage, DocumentLabel
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import AnalysisRun, DocumentVersion, SourceItem
from journeyplus.status_topic.analyzer import STATUS_RELEVANCE_PROMPT_VERSION
from journeyplus.workflow import V1Workflow


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    document_version_id: str
    source_id: str
    document_label: str | None
    event_ids: tuple[str, ...] = ()
    brief_ids: tuple[str, ...] = ()
    reused_classification: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingSummary:
    selected: int
    attempted: int
    succeeded: int
    failed: int
    status_opportunities: int
    events: int
    briefs: int
    documents: tuple[DocumentProcessingResult, ...]
    stopped_early: bool = False


def pending_documents(
    session: Session,
    provider: AIProvider,
    *,
    source_id: str | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
    limit: int = 10,
) -> list[tuple[UUID, str]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    current_analysis_exists = _current_analysis_exists(provider)
    statement = (
        select(DocumentVersion.id, SourceItem.source_id)
        .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
        .where(~current_analysis_exists)
        .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        .limit(limit)
    )
    if source_id is not None and source_ids is not None:
        raise ValueError("source_id and source_ids are mutually exclusive")
    if source_id is not None:
        statement = statement.where(SourceItem.source_id == source_id)
    if source_ids is not None:
        statement = statement.where(SourceItem.source_id.in_(source_ids))
    if published_from is not None:
        statement = statement.where(SourceItem.published_at >= published_from)
    if published_until is not None:
        statement = statement.where(SourceItem.published_at < published_until)
    return [
        (document_id, item_source_id)
        for document_id, item_source_id in session.execute(statement)
    ]


def pending_document_count(
    session: Session,
    provider: AIProvider,
    *,
    source_id: str | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
) -> int:
    statement = (
        select(func.count())
        .select_from(DocumentVersion)
        .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
        .where(~_current_analysis_exists(provider))
    )
    if source_id is not None and source_ids is not None:
        raise ValueError("source_id and source_ids are mutually exclusive")
    if source_id is not None:
        statement = statement.where(SourceItem.source_id == source_id)
    if source_ids is not None:
        statement = statement.where(SourceItem.source_id.in_(source_ids))
    if published_from is not None:
        statement = statement.where(SourceItem.published_at >= published_from)
    if published_until is not None:
        statement = statement.where(SourceItem.published_at < published_until)
    return int(session.scalar(statement) or 0)


def _current_analysis_exists(provider: AIProvider):
    return exists(
        select(AnalysisRun.id).where(
            AnalysisRun.document_version_id == DocumentVersion.id,
            AnalysisRun.stage == AnalysisStage.STATUS_RELEVANCE,
            AnalysisRun.model_config_version == provider.metadata.config_version,
            AnalysisRun.prompt_version == STATUS_RELEVANCE_PROMPT_VERSION,
            AnalysisRun.result.is_not(None),
        )
    )


def process_pending_documents(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    source_id: str | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
    limit: int = 10,
    stop_on_failure: bool = False,
) -> ProcessingSummary:
    with session_factory() as session:
        selected = pending_documents(
            session,
            provider,
            source_id=source_id,
            source_ids=source_ids,
            published_from=published_from,
            published_until=published_until,
            limit=limit,
        )

    runner = JobRunner(session_factory, max_attempts=1)
    results: list[DocumentProcessingResult] = []
    attempted = 0
    stopped_early = False
    for document_id, item_source_id in selected:
        attempted += 1

        def operation(
            current_document_id: UUID = document_id,
            current_source_id: str = item_source_id,
        ) -> DocumentProcessingResult:
            with session_factory.begin() as session:
                document = session.get(DocumentVersion, current_document_id)
                if document is None:
                    raise LookupError(
                        f"Document version {current_document_id} was not found"
                    )
                workflow_result = V1Workflow(session, provider).process(document)
                return DocumentProcessingResult(
                    document_version_id=str(current_document_id),
                    source_id=current_source_id,
                    document_label=workflow_result.document.relevance.result.label,
                    event_ids=tuple(
                        str(item.event.id) for item in workflow_result.document.events
                    ),
                    brief_ids=tuple(
                        str(item.brief.record.id) for item in workflow_result.outputs
                    ),
                    reused_classification=workflow_result.document.relevance.reused,
                )

        try:
            result, skipped = runner.execute(
                idempotency_key=(
                    f"v1-workflow:{document_id}:"
                    f"{provider.metadata.config_version}:"
                    f"{STATUS_RELEVANCE_PROMPT_VERSION}"
                ),
                job_type="v1_document_workflow",
                operation=operation,
                serialize=asdict,
            )
            if skipped or result is None:
                continue
            results.append(result)
        except Exception as exc:
            results.append(
                DocumentProcessingResult(
                    document_version_id=str(document_id),
                    source_id=item_source_id,
                    document_label=None,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            )
            if stop_on_failure:
                stopped_early = attempted < len(selected)
                break

    return ProcessingSummary(
        selected=len(selected),
        attempted=attempted,
        succeeded=sum(item.error is None for item in results),
        failed=sum(item.error is not None for item in results),
        status_opportunities=sum(
            item.document_label == DocumentLabel.STATUS_OPPORTUNITY
            for item in results
        ),
        events=sum(len(item.event_ids) for item in results),
        briefs=sum(len(item.brief_ids) for item in results),
        documents=tuple(results),
        stopped_early=stopped_early,
    )
