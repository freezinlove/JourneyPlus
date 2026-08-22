from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.clustering.aggregator import AggregationResult, EventAggregator
from journeyplus.clustering.relationship import EventRelationshipAnalyzer
from journeyplus.clustering.retrieval import CandidateRetriever
from journeyplus.contracts import DocumentLabel
from journeyplus.models import DocumentVersion
from journeyplus.status_topic.analyzer import RelevanceAnalysis, StatusRelevanceAnalyzer


@dataclass(frozen=True, slots=True)
class DocumentPipelineResult:
    relevance: RelevanceAnalysis
    events: list[AggregationResult]


class StatusOpportunityPipeline:
    def __init__(self, session: Session, provider: AIProvider) -> None:
        self._relevance = StatusRelevanceAnalyzer(session, provider)
        self._retriever = CandidateRetriever(session)
        self._relationship = EventRelationshipAnalyzer(session, provider)
        self._aggregator = EventAggregator(session)

    def process(self, document: DocumentVersion) -> DocumentPipelineResult:
        relevance = self._relevance.analyze(document)
        if relevance.result.label != DocumentLabel.STATUS_OPPORTUNITY:
            return DocumentPipelineResult(relevance, [])
        events: list[AggregationResult] = []
        for index, hint in enumerate(relevance.result.event_hints):
            existing = self._aggregator.existing(
                document=document, hint_index=index
            )
            if existing is not None:
                events.append(existing)
                continue
            candidates = self._retriever.retrieve(hint, document=document)
            relationship = self._relationship.analyze(
                document=document,
                hint=hint,
                hint_index=index,
                candidates=candidates,
            )
            events.append(
                self._aggregator.apply(
                    document=document,
                    hint=hint,
                    hint_index=index,
                    relationship=relationship.result,
                    relationship_run=relationship.run,
                )
            )
        return DocumentPipelineResult(relevance, events)
