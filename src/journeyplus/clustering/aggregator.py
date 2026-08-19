from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import EventHint, RelationshipResult, RelationshipType
from journeyplus.models import (
    AnalysisRun,
    DocumentVersion,
    EventEvidence,
    EventRevision,
    StatusEvent,
)


@dataclass(frozen=True, slots=True)
class AggregationResult:
    event: StatusEvent
    created: bool
    needs_review: bool


class EventAggregator:
    def __init__(self, session: Session) -> None:
        self._session = session

    def existing(
        self, *, document: DocumentVersion, hint_index: int
    ) -> AggregationResult | None:
        evidence = self._session.scalar(
            select(EventEvidence).where(
                EventEvidence.document_version_id == document.id,
                EventEvidence.hint_index == hint_index,
            )
        )
        if evidence is None:
            return None
        event = self._session.get(StatusEvent, evidence.event_id)
        assert event is not None
        return AggregationResult(event, False, event.status == "NEEDS_REVIEW")

    def apply(
        self,
        *,
        document: DocumentVersion,
        hint: EventHint,
        hint_index: int,
        relationship: RelationshipResult,
        relationship_run: AnalysisRun | None = None,
    ) -> AggregationResult:
        existing = self.existing(document=document, hint_index=hint_index)
        if existing is not None:
            return existing

        candidate = (
            self._session.get(StatusEvent, relationship.candidate_event_id)
            if relationship.candidate_event_id
            else None
        )
        created = False
        needs_review = relationship.relationship == RelationshipType.UNCERTAIN
        if relationship.relationship in {
            RelationshipType.SAME_EVENT,
            RelationshipType.UPDATE_OF,
        } and candidate is not None:
            event = candidate
        else:
            created_from_key = f"{document.id}:{hint_index}"
            event = self._session.scalar(
                select(StatusEvent).where(
                    StatusEvent.created_from_key == created_from_key
                )
            )
            if event is None:
                event = StatusEvent(
                    created_from_key=created_from_key,
                    program=hint.program,
                    opportunity_type=hint.opportunity_type,
                    target_status=hint.target_status,
                    summary=hint.summary,
                    search_text=" ".join(
                        value
                        for value in (
                            hint.program,
                            hint.opportunity_type,
                            hint.target_status,
                            hint.summary,
                            hint.region_hint,
                        )
                        if value
                    ),
                    status="NEEDS_REVIEW" if needs_review else "DRAFT",
                )
                self._session.add(event)
                self._session.flush()
                created = True

        evidence = EventEvidence(
            event_id=event.id,
            document_version_id=document.id,
            hint_index=hint_index,
            source_url=document.canonical_url,
            locator=hint.summary,
        )
        self._session.add(evidence)
        revision = EventRevision(
            event_id=event.id,
            document_version_id=document.id,
            relationship=relationship.relationship,
            snapshot={
                "hint": hint.model_dump(mode="json"),
                "relationship": relationship.model_dump(mode="json"),
            },
        )
        self._session.add(revision)
        if relationship_run is not None:
            relationship_run.event_id = event.id
        self._session.flush()
        return AggregationResult(event, created, needs_review)
