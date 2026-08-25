from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.briefs.service import BRIEF_PROMPT_VERSION, BRIEF_SCHEMA_VERSION
from journeyplus.clustering.relationship import (
    RELATIONSHIP_PROMPT_VERSION,
    RELATIONSHIP_SCHEMA_VERSION,
)
from journeyplus.contracts import DocumentLabel
from journeyplus.facts.service import FACT_PROMPT_VERSION, FACT_SCHEMA_VERSION
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import DocumentVersion, JobRun, SourceItem
from journeyplus.statusmatch.articles import is_third_party_statusmatch_article
from journeyplus.status_topic.analyzer import (
    STATUS_RELEVANCE_PROMPT_VERSION,
    STATUS_RELEVANCE_SCHEMA_VERSION,
)
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
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
    limit: int = 10,
) -> list[tuple[UUID, str]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    return _pending_document_rows(
        session,
        provider,
        source_id=source_id,
        source_ids=source_ids,
        document_ids=document_ids,
        published_from=published_from,
        published_until=published_until,
    )[:limit]


def _candidate_document_rows(
    session: Session,
    *,
    source_id: str | None,
    source_ids: list[str] | tuple[str, ...] | None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None,
    published_from: datetime | None,
    published_until: datetime | None,
) -> list[tuple[UUID, str]]:
    if source_id is not None and source_ids is not None:
        raise ValueError("source_id and source_ids are mutually exclusive")
    normalized_document_ids = (
        [UUID(str(value)) for value in document_ids]
        if document_ids is not None
        else None
    )
    if normalized_document_ids == []:
        return []
    statement = (
        select(DocumentVersion.id, SourceItem.source_id)
        .join(SourceItem, SourceItem.id == DocumentVersion.source_item_id)
        .where(
            or_(
                SourceItem.source_id != "status_services_mail",
                ~SourceItem.external_id.startswith("statusmatch-page:"),
            )
        )
        .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
    )
    if source_id is not None:
        statement = statement.where(SourceItem.source_id == source_id)
    if source_ids is not None:
        statement = statement.where(SourceItem.source_id.in_(source_ids))
    if normalized_document_ids is not None:
        statement = statement.where(DocumentVersion.id.in_(normalized_document_ids))
    else:
        newer = aliased(DocumentVersion)
        latest_document_id = (
            select(newer.id)
            .where(newer.source_item_id == DocumentVersion.source_item_id)
            .order_by(newer.created_at.desc(), newer.id.desc())
            .limit(1)
            .correlate(DocumentVersion)
            .scalar_subquery()
        )
        statement = statement.where(DocumentVersion.id == latest_document_id)
    if published_from is not None:
        statement = statement.where(SourceItem.published_at >= published_from)
    if published_until is not None:
        statement = statement.where(SourceItem.published_at < published_until)
    return [
        (document_id, item_source_id)
        for document_id, item_source_id in session.execute(statement)
    ]


def _pending_document_rows(
    session: Session,
    provider: AIProvider,
    *,
    source_id: str | None,
    source_ids: list[str] | tuple[str, ...] | None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None,
    published_from: datetime | None,
    published_until: datetime | None,
) -> list[tuple[UUID, str]]:
    candidates = _candidate_document_rows(
        session,
        source_id=source_id,
        source_ids=source_ids,
        document_ids=document_ids,
        published_from=published_from,
        published_until=published_until,
    )
    candidates = [
        (document_id, item_source_id)
        for document_id, item_source_id in candidates
        if (
            (document := session.get(DocumentVersion, document_id)) is not None
            and not is_third_party_statusmatch_article(session, document)
        )
    ]
    keys = [
        workflow_idempotency_key(document_id, provider)
        for document_id, _ in candidates
    ]
    completed: set[str] = set()
    for start in range(0, len(keys), 500):
        completed.update(
            session.scalars(
                select(JobRun.idempotency_key).where(
                    JobRun.idempotency_key.in_(keys[start : start + 500]),
                    JobRun.status == "SUCCEEDED",
                )
            )
        )
    return [
        row
        for row, key in zip(candidates, keys, strict=True)
        if key not in completed
    ]


def pending_document_count(
    session: Session,
    provider: AIProvider,
    *,
    source_id: str | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
    published_from: datetime | None = None,
    published_until: datetime | None = None,
) -> int:
    return len(
        _pending_document_rows(
            session,
            provider,
            source_id=source_id,
            source_ids=source_ids,
            document_ids=document_ids,
            published_from=published_from,
            published_until=published_until,
        )
    )


def workflow_idempotency_key(document_id: UUID, provider: AIProvider) -> str:
    version_payload = {
        "provider": provider.metadata.config_version,
        "status": [
            STATUS_RELEVANCE_PROMPT_VERSION,
            STATUS_RELEVANCE_SCHEMA_VERSION,
        ],
        "relationship": [
            RELATIONSHIP_PROMPT_VERSION,
            RELATIONSHIP_SCHEMA_VERSION,
        ],
        "facts": [FACT_PROMPT_VERSION, FACT_SCHEMA_VERSION],
        "brief": [BRIEF_PROMPT_VERSION, BRIEF_SCHEMA_VERSION],
    }
    fingerprint = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True).encode()
    ).hexdigest()[:20]
    return f"v1-workflow:{document_id}:{fingerprint}"


def process_pending_documents(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    source_id: str | None = None,
    source_ids: list[str] | tuple[str, ...] | None = None,
    document_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
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
            document_ids=document_ids,
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
                idempotency_key=workflow_idempotency_key(document_id, provider),
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
