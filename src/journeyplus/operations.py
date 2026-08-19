from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage, RelevanceLabel
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import AnalysisRun, DocumentVersion, SourceItem
from journeyplus.status_topic.analyzer import STATUS_RELEVANCE_PROMPT_VERSION
from journeyplus.workflow import V1Workflow


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    document_version_id: str
    source_id: str
    relevance: str | None
    event_ids: tuple[str, ...] = ()
    brief_ids: tuple[str, ...] = ()
    reused_relevance: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingSummary:
    selected: int
    succeeded: int
    failed: int
    relevant: int
    events: int
    briefs: int
    documents: tuple[DocumentProcessingResult, ...]


def pending_documents(
    session: Session,
    provider: AIProvider,
    *,
    source_id: str | None = None,
    limit: int = 10,
) -> list[tuple[UUID, str]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    current_analysis_exists = exists(
        select(AnalysisRun.id).where(
            AnalysisRun.document_version_id == DocumentVersion.id,
            AnalysisRun.stage == AnalysisStage.STATUS_RELEVANCE,
            AnalysisRun.model_config_version == provider.metadata.config_version,
            AnalysisRun.prompt_version == STATUS_RELEVANCE_PROMPT_VERSION,
            AnalysisRun.result.is_not(None),
        )
    )
    statement = (
        select(DocumentVersion.id, SourceItem.source_id)
        .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
        .where(~current_analysis_exists)
        .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        .limit(limit)
    )
    if source_id is not None:
        statement = statement.where(SourceItem.source_id == source_id)
    return [
        (document_id, item_source_id)
        for document_id, item_source_id in session.execute(statement)
    ]


def process_pending_documents(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    source_id: str | None = None,
    limit: int = 10,
) -> ProcessingSummary:
    with session_factory() as session:
        selected = pending_documents(
            session, provider, source_id=source_id, limit=limit
        )

    runner = JobRunner(session_factory, max_attempts=1)
    results: list[DocumentProcessingResult] = []
    for document_id, item_source_id in selected:

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
                    relevance=workflow_result.document.relevance.result.label,
                    event_ids=tuple(
                        str(item.event.id) for item in workflow_result.document.events
                    ),
                    brief_ids=tuple(
                        str(item.brief.record.id) for item in workflow_result.outputs
                    ),
                    reused_relevance=workflow_result.document.relevance.reused,
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
                    relevance=None,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            )

    return ProcessingSummary(
        selected=len(selected),
        succeeded=sum(item.error is None for item in results),
        failed=sum(item.error is not None for item in results),
        relevant=sum(item.relevance == RelevanceLabel.YES for item in results),
        events=sum(len(item.event_ids) for item in results),
        briefs=sum(len(item.brief_ids) for item in results),
        documents=tuple(results),
    )
