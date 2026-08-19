from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.briefs.service import BriefGeneration, BriefGenerator
from journeyplus.facts.service import FactConsolidation, FactConsolidator
from journeyplus.models import DocumentVersion
from journeyplus.status_topic.pipeline import DocumentPipelineResult, StatusOpportunityPipeline


@dataclass(frozen=True, slots=True)
class EventOutput:
    facts: FactConsolidation
    brief: BriefGeneration


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    document: DocumentPipelineResult
    outputs: list[EventOutput]


class V1Workflow:
    """Thin application orchestration; each stage remains independently callable."""

    def __init__(self, session: Session, provider: AIProvider) -> None:
        self._status = StatusOpportunityPipeline(session, provider)
        self._facts = FactConsolidator(session, provider)
        self._briefs = BriefGenerator(session, provider)

    def process(self, document: DocumentVersion) -> WorkflowResult:
        status_result = self._status.process(document)
        outputs: list[EventOutput] = []
        seen_events = set()
        for aggregated in status_result.events:
            if aggregated.event.id in seen_events:
                continue
            seen_events.add(aggregated.event.id)
            facts = self._facts.consolidate(aggregated.event)
            brief = self._briefs.generate(facts.record)
            outputs.append(EventOutput(facts, brief))
        return WorkflowResult(status_result, outputs)

