from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.briefs.service import BriefGeneration, BriefGenerator
from journeyplus.contracts import FactSet, ReviewAction
from journeyplus.models import (
    AnalysisRun,
    BriefRecord,
    DocumentVersion,
    EventEvidence,
    EventRevision,
    FactSetRecord,
    ReviewDecision,
    StatusEvent,
)


@dataclass(frozen=True, slots=True)
class ReviewResult:
    event: StatusEvent
    decision: ReviewDecision
    created_event: StatusEvent | None = None


class ReviewService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def queue(self) -> list[dict[str, Any]]:
        events = list(
            self._session.scalars(
                select(StatusEvent)
                .where(StatusEvent.status == "NEEDS_REVIEW")
                .order_by(StatusEvent.updated_at.asc())
            )
        )
        failed_runs = list(
            self._session.scalars(
                select(AnalysisRun)
                .where(AnalysisRun.status == "FAILED")
                .order_by(AnalysisRun.created_at.asc())
            )
        )
        return [
            {
                "kind": "event",
                "id": str(event.id),
                "program": event.program,
                "reason": "uncertain relationship or conflicting facts",
            }
            for event in events
        ] + [
            {
                "kind": "analysis_run",
                "id": str(run.id),
                "stage": run.stage,
                "reason": run.error,
            }
            for run in failed_runs
        ]

    def full_chain(self, event_id: UUID) -> dict[str, Any]:
        event = self._event(event_id)
        evidence = list(
            self._session.scalars(
                select(EventEvidence).where(EventEvidence.event_id == event.id)
            )
        )
        document_ids = [item.document_version_id for item in evidence]
        documents = (
            list(
                self._session.scalars(
                    select(DocumentVersion).where(DocumentVersion.id.in_(document_ids))
                )
            )
            if document_ids
            else []
        )
        analyses = list(
            self._session.scalars(
                select(AnalysisRun).where(
                    (AnalysisRun.event_id == event.id)
                    | (AnalysisRun.document_version_id.in_(document_ids or [uuid4()]))
                )
            )
        )
        facts = (
            self._session.get(FactSetRecord, event.current_fact_set_id)
            if event.current_fact_set_id
            else None
        )
        brief = (
            self._session.get(BriefRecord, event.current_brief_id)
            if event.current_brief_id
            else None
        )
        decisions = list(
            self._session.scalars(
                select(ReviewDecision).where(
                    ReviewDecision.entity_type == "status_event",
                    ReviewDecision.entity_id == event.id,
                )
            )
        )
        return {
            "event": _event_dict(event),
            "evidence": [
                {
                    "document_version_id": str(item.document_version_id),
                    "source_url": item.source_url,
                    "locator": item.locator,
                    "hint_index": item.hint_index,
                }
                for item in evidence
            ],
            "documents": [
                {
                    "id": str(document.id),
                    "canonical_url": document.canonical_url,
                    "normalized_body": document.normalized_body,
                    "parser_version": document.parser_version,
                }
                for document in documents
            ],
            "analyses": [
                {
                    "id": str(run.id),
                    "stage": run.stage,
                    "status": run.status,
                    "prompt_version": run.prompt_version,
                    "model_config_version": run.model_config_version,
                    "result": run.result,
                    "error": run.error,
                }
                for run in analyses
            ],
            "fact_set": facts.facts if facts else None,
            "brief": brief.content if brief else None,
            "decisions": [
                {
                    "action": item.action,
                    "reason": item.reason,
                    "actor": item.actor,
                    "payload": item.payload,
                }
                for item in decisions
            ],
        }

    def confirm(
        self,
        event_id: UUID,
        *,
        conflict_resolutions: dict[str, str] | None = None,
        reason: str | None = None,
        actor: str = "operator",
    ) -> ReviewResult:
        event = self._event(event_id)
        if conflict_resolutions:
            self._resolve_conflicts(event, conflict_resolutions)
        current = self._session.get(FactSetRecord, event.current_fact_set_id)
        if current is not None and current.has_conflicts:
            raise ValueError("All fact conflicts must be resolved before confirmation")
        event.status = "CONFIRMED"
        decision = self._decision(
            ReviewAction.CONFIRM,
            event,
            reason=reason,
            actor=actor,
            payload={"conflict_resolutions": conflict_resolutions or {}},
        )
        return ReviewResult(event, decision)

    def reject(
        self,
        event_id: UUID,
        *,
        reason: str | None = None,
        actor: str = "operator",
    ) -> ReviewResult:
        event = self._event(event_id)
        event.status = "REJECTED"
        decision = self._decision(
            ReviewAction.REJECT, event, reason=reason, actor=actor
        )
        return ReviewResult(event, decision)

    def merge(
        self,
        source_event_id: UUID,
        target_event_id: UUID,
        *,
        reason: str | None = None,
        actor: str = "operator",
    ) -> ReviewResult:
        if source_event_id == target_event_id:
            raise ValueError("Cannot merge an event into itself")
        source = self._event(source_event_id)
        target = self._event(target_event_id)
        for evidence in list(
            self._session.scalars(
                select(EventEvidence).where(EventEvidence.event_id == source.id)
            )
        ):
            duplicate = self._session.scalar(
                select(EventEvidence).where(
                    EventEvidence.event_id == target.id,
                    EventEvidence.document_version_id == evidence.document_version_id,
                    EventEvidence.hint_index == evidence.hint_index,
                )
            )
            if duplicate:
                self._session.delete(evidence)
            else:
                evidence.event_id = target.id
        for revision in list(
            self._session.scalars(
                select(EventRevision).where(EventRevision.event_id == source.id)
            )
        ):
            duplicate = self._session.scalar(
                select(EventRevision).where(
                    EventRevision.event_id == target.id,
                    EventRevision.document_version_id == revision.document_version_id,
                    EventRevision.relationship == revision.relationship,
                )
            )
            if duplicate:
                self._session.delete(revision)
            else:
                revision.event_id = target.id
        source.merged_into_id = target.id
        source.status = "MERGED"
        target.current_fact_set_id = None
        target.current_brief_id = None
        decision = self._decision(
            ReviewAction.MERGE,
            source,
            target=target,
            reason=reason,
            actor=actor,
        )
        self._session.flush()
        return ReviewResult(source, decision, target)

    def split(
        self,
        event_id: UUID,
        document_version_ids: list[UUID],
        *,
        reason: str | None = None,
        actor: str = "operator",
    ) -> ReviewResult:
        event = self._event(event_id)
        selected = set(document_version_ids)
        if not selected:
            raise ValueError("A split requires at least one document version")
        evidence = list(
            self._session.scalars(
                select(EventEvidence).where(EventEvidence.event_id == event.id)
            )
        )
        available = {item.document_version_id for item in evidence}
        if not selected <= available:
            raise ValueError("Split contains documents outside the event")
        if selected == available:
            raise ValueError("A split must leave evidence on the original event")
        created = StatusEvent(
            created_from_key=f"review-split:{event.id}:{uuid4()}",
            program=event.program,
            opportunity_type=event.opportunity_type,
            target_status=event.target_status,
            summary=event.summary,
            search_text=event.search_text,
            status="DRAFT",
        )
        self._session.add(created)
        self._session.flush()
        for item in evidence:
            if item.document_version_id in selected:
                item.event_id = created.id
        for revision in self._session.scalars(
            select(EventRevision).where(
                EventRevision.event_id == event.id,
                EventRevision.document_version_id.in_(selected),
            )
        ):
            revision.event_id = created.id
        event.current_fact_set_id = None
        event.current_brief_id = None
        created.current_fact_set_id = None
        created.current_brief_id = None
        decision = self._decision(
            ReviewAction.SPLIT,
            event,
            target=created,
            reason=reason,
            actor=actor,
            payload={"document_version_ids": [str(item) for item in selected]},
        )
        self._session.flush()
        return ReviewResult(event, decision, created)

    def regenerate_brief(
        self,
        event_id: UUID,
        provider: AIProvider,
        *,
        reason: str | None = None,
        actor: str = "operator",
    ) -> tuple[ReviewResult, BriefGeneration]:
        event = self._event(event_id)
        fact_record = self._session.get(FactSetRecord, event.current_fact_set_id)
        if fact_record is None:
            raise ValueError("Event has no current FactSet")
        generation = BriefGenerator(
            self._session,
            provider,
            prompt_version=f"review-regenerate:{uuid4()}",
        ).generate(fact_record)
        decision = self._decision(
            ReviewAction.REGENERATE, event, reason=reason, actor=actor
        )
        return ReviewResult(event, decision), generation

    def _resolve_conflicts(
        self, event: StatusEvent, resolutions: dict[str, str]
    ) -> FactSetRecord:
        current = self._session.get(FactSetRecord, event.current_fact_set_id)
        if current is None:
            raise ValueError("Event has no FactSet to resolve")
        facts = FactSet.model_validate(current.facts)
        fields = facts.fact_fields()
        for key, selected_value in resolutions.items():
            if key not in fields or not fields[key].conflict:
                raise ValueError(f"Fact field is not conflicted: {key}")
            if selected_value not in fields[key].alternatives:
                raise ValueError(f"Resolution is not a recorded alternative: {key}")
            fields[key].value = selected_value
            fields[key].conflict = False
            fields[key].alternatives = []
        resolved = FactSet.model_validate(facts.model_dump(mode="json"))
        remaining = any(field.conflict for field in resolved.fact_fields().values())
        version = (
            self._session.scalar(
                select(func.max(FactSetRecord.version)).where(
                    FactSetRecord.event_id == event.id
                )
            )
            or 0
        ) + 1
        record = FactSetRecord(
            event_id=event.id,
            version=version,
            schema_version=resolved.schema_version,
            facts=resolved.model_dump(mode="json"),
            has_conflicts=remaining,
        )
        self._session.add(record)
        self._session.flush()
        event.current_fact_set_id = record.id
        event.current_brief_id = None
        return record

    def _decision(
        self,
        action: ReviewAction,
        event: StatusEvent,
        *,
        target: StatusEvent | None = None,
        reason: str | None = None,
        actor: str = "operator",
        payload: dict[str, Any] | None = None,
    ) -> ReviewDecision:
        decision = ReviewDecision(
            action=action,
            entity_type="status_event",
            entity_id=event.id,
            target_entity_id=target.id if target else None,
            reason=reason,
            actor=actor,
            payload=payload or {},
        )
        self._session.add(decision)
        self._session.flush()
        return decision

    def _event(self, event_id: UUID) -> StatusEvent:
        event = self._session.get(StatusEvent, event_id)
        if event is None:
            raise LookupError(f"Status event was not found: {event_id}")
        return event


def _event_dict(event: StatusEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "program": event.program,
        "opportunity_type": event.opportunity_type,
        "target_status": event.target_status,
        "summary": event.summary,
        "status": event.status,
        "merged_into_id": str(event.merged_into_id) if event.merged_into_id else None,
        "current_fact_set_id": (
            str(event.current_fact_set_id) if event.current_fact_set_id else None
        ),
        "current_brief_id": str(event.current_brief_id) if event.current_brief_id else None,
    }
